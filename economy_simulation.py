"""
Aeloria faction economic simulation — resources, per-tick flow, and shortage effects.

Designed to be extended: add new resource IDs in CORE_RESOURCES, register shortage
handlers, or plug in custom production/consumption estimators.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from engine.causality import record_cause

# --- Resource model ---------------------------------------------------------------------------

CORE_RESOURCES: Tuple[str, ...] = ("grain", "iron", "timber", "gold")

# Numeraire index at equilibrium (demand / supply = 1). Used for world market pricing.
BASE_PRICE: Dict[str, float] = {
    "grain": 1.0,
    "timber": 2.0,
    "iron": 3.0,
    "gold": 5.0,
}
PRICE_FLOOR_MULT = 0.5
PRICE_CAP_MULT = 3.0
MARKET_TRADABLE: Tuple[str, ...] = ("grain", "iron", "timber")  # paid from / to gold stockpile

# Scale: stockpiles and capacities use abstract "units" (not gold pieces); keep numbers comparable.
DEFAULT_STORAGE: Dict[str, int] = {
    "grain": 8000,
    "iron": 4000,
    "timber": 5000,
    "gold": 3000,
}

# Tunable: how strongly shortages push secondary world fields (0..1)
SHORTAGE_STRENGTH = 0.6


@dataclass
class ResourceFlow:
    production: float = 0.0
    consumption: float = 0.0
    stockpile: float = 0.0
    storage_capacity: int = 0

    def to_record(self) -> Dict[str, Any]:
        return {
            "production": round(self.production, 2),
            "consumption": round(self.consumption, 2),
            "stockpile": int(round(self.stockpile)),
        }

    def to_full_record(self) -> Dict[str, Any]:
        r = self.to_record()
        r["storage_capacity"] = int(self.storage_capacity)
        return r


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _controlled_region_names(faction: str, state: dict) -> Set[str]:
    locs = state.get("locations") or []
    names = {loc.get("name") for loc in locs if loc.get("controller") == faction and loc.get("name")}
    if not names and not locs:
        names = {
            r.get("region")
            for r in state.get("region_control", [])
            if r.get("controller") == faction and r.get("region")
        }
    return {n for n in names if n}


def army_manpower_total(faction: str, state: dict) -> int:
    """Sum of all army manpower for a faction; 0 if no `faction_armies` rows."""
    s = 0
    for a in state.get("faction_armies") or []:
        if (a.get("faction_id") or a.get("faction")) == faction:
            s += int(a.get("manpower", 0) or 0)
    return max(0, s)


def _population_aggregates(faction: str, state: dict) -> Tuple[int, int, int]:
    """Total population, active military, naval allocation (0..100) for a faction's regions.

    When `faction_armies` lists at least one unit for the faction, military headcount
    is taken as the sum of army manpower (replaces population activeMilitary for economy).
    """
    pop_rows = state.get("population_state") or []
    regions = _controlled_region_names(faction, state)
    rows: List[dict] = []
    for p in pop_rows:
        r = p.get("region", "")
        cult = p.get("culture", "")
        if r in regions or cult == faction or faction in str(cult):
            rows.append(p)
    if not rows:
        for p in pop_rows:
            if p.get("culture") and faction.split()[0] in p.get("culture", ""):
                rows.append(p)
    if not rows:
        return 1000, 10, 0
    pop = sum(int(p.get("population", 0)) for p in rows)
    mil = sum(int(p.get("activeMilitary", 0)) for p in rows)
    aw = army_manpower_total(faction, state)
    if aw > 0:
        mil = aw
    n_rows = max(1, len(rows))
    naval = int(round(sum(int(p.get("navalAllocation", 0)) for p in rows) / n_rows))
    return max(1, pop), max(0, mil), max(0, min(100, naval))


def _estimate_production(
    res: str,
    faction: str,
    state: dict,
    total_pop: int,
    active_mil: int,
    naval: int,
) -> float:
    """Heuristic baselines; override via world hooks later."""
    locs = [loc for loc in (state.get("locations") or []) if loc.get("controller") == faction]
    n_regions = max(1, len(locs))
    rural = sum(1 for loc in locs if str(loc.get("region_type", "")).lower() in ("farmland", "wilderness", "plains", "hills", "heath"))
    ports = sum(1 for loc in locs if str(loc.get("region_type", "")).lower() in ("coast", "port", "isles", "archipelago", "island", "bays", "bays_"))

    if res == "grain":
        return 120.0 + n_regions * 45.0 + rural * 25.0 + (total_pop / 800.0) * 1.1
    if res == "iron":
        return 50.0 + n_regions * 20.0 + (active_mil / 200.0) * 3.0
    if res == "timber":
        return 80.0 + n_regions * 30.0 + rural * 18.0 + (naval / 12.0) * 1.0
    if res == "gold":
        return 40.0 + n_regions * 15.0 + ports * 35.0 + (total_pop / 1200.0) * 1.0
    return 0.0


def _estimate_consumption(
    res: str,
    total_pop: int,
    active_mil: int,
    naval: int,
) -> float:
    if res == "grain":
        return (total_pop / 1000.0) * 18.0 + (active_mil / 100.0) * 2.0
    if res == "iron":
        return (active_mil / 100.0) * 5.0
    if res == "timber":
        return (active_mil / 100.0) * 1.2 + (naval / 8.0) * 0.4
    if res == "gold":
        return 25.0 + (total_pop / 1000.0) * 2.0 + (active_mil / 100.0) * 0.5
    return 0.0


# --- Shortage side effects --------------------------------------------------------------------

ShortageHandler = Callable[[str, float, dict], None]


def _effect_grain(faction: str, severity: float, state: dict) -> None:
    if severity <= 0:
        return
    pop_state = state.setdefault("population_state", [])
    regions = _controlled_region_names(faction, state)
    affected_regions: List[str] = []
    total_loss = 0
    max_pressure_after = 0
    for row in pop_state:
        r = row.get("region", "")
        if regions and r not in regions:
            continue
        p = int(row.get("pressure", 50))
        row["pressure"] = int(_clamp(p + 2 + 8 * severity * SHORTAGE_STRENGTH, 0, 100))
        max_pressure_after = max(max_pressure_after, int(row.get("pressure", 0) or 0))
        pop = int(row.get("population", 0))
        if pop > 0:
            loss = max(1, int(pop * 0.0015 * severity * SHORTAGE_STRENGTH))
            row["population"] = max(0, pop - loss)
            total_loss += max(0, pop - int(row["population"]))
        if r:
            affected_regions.append(str(r))
        g = float(row.get("growthRate", 0.0)) - 0.0001 * severity * SHORTAGE_STRENGTH
        row["growthRate"] = g
    if affected_regions and (severity >= 0.35 or total_loss >= 5 or max_pressure_after >= 75):
        record_cause(
            state,
            domain="population",
            actor=faction,
            pressure=(
                f"grain shortage social stress; severity={round(float(severity), 3)}; "
                f"population_loss={total_loss}; max_pressure={max_pressure_after}"
            ),
            belief="food scarcity is straining households and weakening local order",
            decision="population_food_unrest",
            outcome=(
                f"Food scarcity raises unrest across {faction}'s population centers "
                f"and displaces {total_loss} people."
            ),
            affected=[faction, *affected_regions[:6]],
            hidden=None,
            severity=int(_clamp(6 + severity * 6 + min(3, total_loss / 20), 6, 12)),
            confidence=0.88,
            source="economy_simulation",
        )


def _effect_timber(faction: str, severity: float, state: dict) -> None:
    if severity <= 0:
        return
    for row in state.get("population_state", []) or []:
        r = row.get("region", "")
        if r in _controlled_region_names(faction, state) or row.get("culture") == faction:
            n = int(row.get("navalAllocation", 0))
            row["navalAllocation"] = int(_clamp(n - 1 - 4 * severity * SHORTAGE_STRENGTH, 0, 100))


def _effect_gold(faction: str, severity: float, state: dict) -> None:
    if severity <= 0:
        return
    for route in state.get("trade_routes", []) or []:
        if route.get("from") == faction or route.get("to") == faction:
            st = str(route.get("status", "active"))
            if st not in ("blocked", "disrupted"):
                route["status"] = "strained" if random.random() < 0.5 * severity + 0.2 else st
    for row in state.get("population_state", []) or []:
        if row.get("region", "") in _controlled_region_names(faction, state):
            pr = int(row.get("pressure", 50))
            row["pressure"] = int(_clamp(pr + 1 + 4 * severity * SHORTAGE_STRENGTH, 0, 100))


_SHORTAGE_HANDLERS: Dict[str, ShortageHandler] = {
    "grain": _effect_grain,
    "timber": _effect_timber,
    "gold": _effect_gold,
}


# --- World market (dynamic prices, voluntary trade) -----------------------------------------

def _aggregate_market_flows(faction_economy: List[dict]) -> Tuple[Dict[str, float], Dict[str, float]]:
    S = {r: 0.0 for r in CORE_RESOURCES}
    D = {r: 0.0 for r in CORE_RESOURCES}
    for row in faction_economy:
        for r in CORE_RESOURCES:
            res = (row.get("resources") or {}).get(r) or {}
            S[r] += max(0.0, float(res.get("stockpile", 0) or 0))
            D[r] += max(0.0, float(res.get("consumption", 0) or 0))
    return S, D


def _compute_market_prices(aggregate_s: dict, aggregate_d: dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in CORE_RESOURCES:
        b = float(BASE_PRICE[r])
        s = max(1.0, float(aggregate_s.get(r, 0.0) or 0.0))
        d = max(1.0, float(aggregate_d.get(r, 0.0) or 0.0))
        raw = b * (d / s)
        out[r] = float(_clamp(raw, b * PRICE_FLOOR_MULT, b * PRICE_CAP_MULT))
    return out


def _apply_disruption_to_prices(
    base_prices: Dict[str, float], disruption_mult: float, state: dict
) -> Dict[str, float]:
    """Widen or spike prices when trade routes are disrupted; siege / blockade adds import cost."""
    m0 = _clamp(float(disruption_mult or 1.0), 0.8, 1.45)
    siege = _clamp(float(state.get("siege_import_mult", 1.0) or 1.0), 0.9, 1.45)
    stress = 1.0 + _clamp(float(state.get("siege_stress_add", 0) or 0), 0, 0.25)
    out: Dict[str, float] = {}
    for r in CORE_RESOURCES:
        b = float(BASE_PRICE[r])
        p0 = float(base_prices.get(r, b))
        import_bias = 1.06 if r in ("grain", "iron", "timber") else 1.0
        m = m0 * siege * stress * (import_bias * 0.15 + 0.85)
        out[r] = float(_clamp(p0 * m, b * PRICE_FLOOR_MULT, b * PRICE_CAP_MULT))
    return out


def _record_market_shock_cause(
    state: dict,
    *,
    prices: Dict[str, float],
    aggregate_supply: Dict[str, float],
    aggregate_demand: Dict[str, float],
    price_spike_mult: float,
) -> None:
    pressure_by_resource: Dict[str, float] = {}
    for res in MARKET_TRADABLE:
        base = max(0.01, float(BASE_PRICE.get(res, 1.0)))
        price_mult = float(prices.get(res, base)) / base
        demand_pressure = float(aggregate_demand.get(res, 0.0) or 0.0) / max(
            1.0, float(aggregate_supply.get(res, 0.0) or 0.0)
        )
        pressure_by_resource[res] = max(price_mult, demand_pressure)

    if not pressure_by_resource:
        return

    resource, pressure_score = max(pressure_by_resource.items(), key=lambda item: item[1])
    spike = float(price_spike_mult or 1.0)
    if spike < 1.12 and pressure_score < 1.75:
        return

    affected: List[str] = []
    for row in state.get("faction_economy", []) or []:
        faction = row.get("faction_id") or row.get("faction")
        if not faction:
            continue
        shortage = float(
            ((row.get("shortage_effects") or {}).get(resource) or {}).get("severity", 0.0)
            or 0.0
        )
        trades = row.get("trades") or []
        touched_market = any(t.get("resource") == resource for t in trades if isinstance(t, dict))
        if shortage >= 0.15 or touched_market:
            affected.append(str(faction))
    if not affected:
        affected = [str(row.get("faction_id") or row.get("faction")) for row in state.get("faction_economy", []) or [] if row.get("faction_id") or row.get("faction")]

    severity = int(_clamp(5 + (spike - 1.0) * 18 + max(0.0, pressure_score - 1.0) * 2, 5, 10))
    record_cause(
        state,
        domain="economy",
        actor="World Market",
        pressure=(
            f"{resource} market shock; price_mult={round(float(prices.get(resource, BASE_PRICE[resource])) / BASE_PRICE[resource], 3)}; "
            f"demand={round(float(aggregate_demand.get(resource, 0.0) or 0.0), 2)}; "
            f"supply={round(float(aggregate_supply.get(resource, 0.0) or 0.0), 2)}; "
            f"disruption_mult={round(spike, 3)}"
        ),
        belief="scarcity and disrupted trade are pushing market prices into political danger",
        decision="market_price_shock",
        outcome=f"{resource.title()} prices surged under shortage and trade disruption pressure.",
        affected=affected[:8],
        hidden=None,
        severity=severity,
        confidence=0.86,
        source="economy_simulation",
    )


def _run_resource_market(state: dict) -> None:
    """Set global market prices, then have each faction buy shortfalls and sell surpluses (for gold)."""
    rows: List[dict] = list(state.get("faction_economy") or [])
    if not rows:
        return
    S, D = _aggregate_market_flows(rows)
    base_p = _compute_market_prices(S, D)
    sp = float(_clamp(state.get("economic_disruption_price_mult", 1.0) or 1.0, 0.8, 1.45))
    sab = float(state.get("sabotage_price_stress", 0) or 0)
    sp = float(_clamp(sp * (1.0 + min(0.15, sab)), 0.8, 1.5))
    state.setdefault("siege_import_mult", 1.0)
    state.setdefault("siege_stress_add", 0.0)
    prices = _apply_disruption_to_prices(base_p, sp, state)
    tick = int(state.get("tick", 0))
    state["resource_market"] = {
        "tick": tick,
        "prices": {r: round(float(prices[r]), 4) for r in CORE_RESOURCES},
        "price_spike_mult": round(sp, 4),
        "siege_import_mult": round(float(state.get("siege_import_mult", 1.0) or 1.0), 4),
        "siege_stress": round(float(state.get("siege_stress_add", 0) or 0.0), 4),
        "aggregate_supply": {r: round(float(S[r]), 2) for r in CORE_RESOURCES},
        "aggregate_demand": {r: round(float(D[r]), 2) for r in CORE_RESOURCES},
    }
    _record_market_shock_cause(
        state,
        prices=prices,
        aggregate_supply=S,
        aggregate_demand=D,
        price_spike_mult=sp,
    )

    for row in rows:
        resmap = row.setdefault("resources", {})
        for r in CORE_RESOURCES:
            resmap.setdefault(
                r,
                {
                    "production": 0.0,
                    "consumption": 0.0,
                    "stockpile": 0,
                    "storage_capacity": DEFAULT_STORAGE.get(r, 5000),
                },
            )

        def _c(r: str) -> float:
            return max(0.0, float((resmap.get(r) or {}).get("consumption", 0) or 0))

        def _st(r: str) -> float:
            return max(0.0, float((resmap.get(r) or {}).get("stockpile", 0) or 0))

        def _cp(r: str) -> int:
            return int(max(100, int((resmap.get(r) or {}).get("storage_capacity", DEFAULT_STORAGE.get(r, 5000)) or 5000)))

        trades: List[Dict[str, Any]] = []
        gold = _st("gold")
        g_cap = _cp("gold")
        (resmap.get("gold") or {})["storage_capacity"] = g_cap

        def _overstock(r: str) -> float:
            """Excess in resource units: above ~15× daily flow (abstract buffer)."""
            c, stv = _c(r), _st(r)
            buffer = max(8.0, c * 15.0)
            return max(0.0, stv - buffer)

        # --- buys (priority: food, iron, timber) ------------------------------------------
        want_order: List[Tuple[str, float, float]] = []
        for r in MARKET_TRADABLE:
            c, stv, p = _c(r), _st(r), float(prices.get(r, BASE_PRICE[r]))
            if c < 0.1:
                continue
            # Rebalance toward a modest working buffer (sub-day cover in flow-units, abstract).
            if stv < 0.65 * c:
                need = min(c * 0.22, max(0.0, 0.55 * c - stv * 0.4 + c * 0.05))
            else:
                need = 0.0
            need = min(need, max(0.0, _cp(r) - stv) * 0.99)
            if need > 0.01:
                want_order.append((r, need, p))
        _prio = {MARKET_TRADABLE[i]: i for i in range(len(MARKET_TRADABLE))}
        want_order.sort(key=lambda t: _prio.get(t[0], 9))

        spend_cap = _clamp(gold * 0.4, 0, max(0.0, gold - 1.0))
        spent = 0.0
        for r, need, p in want_order:
            if need < 0.5 or p <= 0 or spend_cap - spent <= 0.01:
                continue
            room = max(0.0, _cp(r) - _st(r))
            max_by_gold = (spend_cap - spent) / p
            qty = int(min(need, max_by_gold, room))
            qty = max(0, qty)
            if qty <= 0:
                continue
            cost = qty * p
            gold = _st("gold")
            if cost > gold - 0.5:
                qty = int(max(0, (gold - 1) / p))
                if qty <= 0:
                    continue
                cost = qty * p
            resmap[r]["stockpile"] = int(_st(r) + qty)
            resmap["gold"]["stockpile"] = int(max(0, _st("gold") - cost))
            gold = _st("gold")
            spent += cost
            trades.append(
                {
                    "action": "buy",
                    "resource": r,
                    "amount": qty,
                    "unit_price": round(p, 4),
                    "total_gold": round(cost, 2),
                }
            )

        # --- sell grain / iron / timber for gold -------------------------------------------
        g_cap = _cp("gold")
        for r in MARKET_TRADABLE:
            stv = _st(r)
            p = float(prices.get(r, BASE_PRICE[r]))
            over = _overstock(r)
            if over < 0.1 or p <= 0:
                continue
            qty = int(min(over * 0.1, stv * 0.04, stv - 1))
            qty = max(0, qty)
            if qty <= 0:
                continue
            rev = qty * p
            resmap[r]["stockpile"] = int(stv - qty)
            g_new = int(min(g_cap, _st("gold") + rev))
            resmap["gold"]["stockpile"] = g_new
            trades.append(
                {
                    "action": "sell",
                    "resource": r,
                    "amount": qty,
                    "unit_price": round(p, 4),
                    "total_gold": round(rev, 2),
                }
            )

        row["trades"] = trades


# --- Public API -------------------------------------------------------------------------------

def list_faction_ids(state: dict) -> List[str]:
    out: Set[str] = set()
    for key in ("faction_identities", "faction_power_state"):
        val = state.get(key)
        if isinstance(val, dict):
            for k in val.keys():
                if k and not str(k).startswith("_"):
                    out.add(k)
        elif isinstance(val, list) and val and key == "faction_power_state":
            for row in val:
                if not isinstance(row, dict):
                    continue
                f = row.get("faction")
                if f:
                    out.add(f)
    if not out:
        for row in state.get("faction_resources", []) or []:
            if not isinstance(row, dict):
                continue
            f = row.get("faction")
            if f:
                out.add(f)
    return sorted(out)


def _default_faction_economy_row(
    faction: str, state: dict, prev: Optional[dict] = None
) -> dict:
    total_pop, active_mil, naval = _population_aggregates(faction, state)
    prev_res = (prev or {}).get("resources") or {}
    resources: Dict[str, Any] = {}
    for r in CORE_RESOURCES:
        prs = prev_res.get(r) or {}
        cap = int(prs.get("storage_capacity", DEFAULT_STORAGE.get(r, 5000)))
        epr = _estimate_production(r, faction, state, total_pop, active_mil, naval)
        eco = _estimate_consumption(r, total_pop, active_mil, naval)
        default_stock = int(cap * 0.55)
        stock = int(prs.get("stockpile", default_stock) if prs else default_stock)
        resources[r] = {
            "production": round(float(prs.get("production", epr)) if prs else epr, 2),
            "consumption": round(float(prs.get("consumption", eco)) if prs else eco, 2),
            "stockpile": int(_clamp(stock, 0, cap)),
            "storage_capacity": cap,
        }
    return {
        "faction_id": faction,
        "resources": resources,
        "shortage_effects": {x: {"severity": 0.0, "unmet_demand": 0.0} for x in CORE_RESOURCES},
        "trades": [],
    }


def _merge_row(prev_row: dict, state: dict) -> dict:
    fid = prev_row.get("faction_id", "")
    if not fid:
        return prev_row
    return _default_faction_economy_row(fid, state, prev_row)


def run_faction_economy_tick(
    state: dict,
    prev_state: Optional[dict] = None,
) -> None:
    """
    Apply one day of production/consumption, compute shortages, apply penalties, and
    mirror a coarse legacy food/materials readout into faction_resources.
    """
    tick = int(state.get("tick", 0))
    if state.get("_economy_engine_tick") == tick:
        return
    state["_economy_engine_tick"] = tick
    ss = float(state.get("sabotage_price_stress", 0) or 0)
    if ss > 0.0005:
        state["sabotage_price_stress"] = round(ss * 0.88, 4)

    from siege_blockade import process_siege_blockade

    process_siege_blockade(state, prev_state or {})

    prev = prev_state or {}
    prev_econ = {
        r.get("faction_id") or r.get("faction"): r
        for r in prev.get("faction_economy", [])
        if r.get("faction_id") or r.get("faction")
    }
    incoming = {
        r.get("faction_id") or r.get("faction"): r
        for r in (state.get("faction_economy") or [])
        if r.get("faction_id") or r.get("faction")
    }
    for fid, row in incoming.items():
        prev_econ[fid] = {**(prev_econ.get(fid) or {}), **row}

    factions = list_faction_ids(state)
    if not factions:
        return

    out_rows: List[dict] = []

    for fid in factions:
        prev_row = prev_econ.get(fid)
        if not prev_row:
            row = _default_faction_economy_row(fid, state, None)
        else:
            if not prev_row.get("resources"):
                row = _merge_row({**prev_row, "faction_id": fid}, state)
            else:
                row = {**prev_row, "faction_id": fid}

        if "shortage_effects" not in row:
            row["shortage_effects"] = {x: {"severity": 0.0, "unmet_demand": 0.0} for x in CORE_RESOURCES}

        total_pop, active_mil, naval = _population_aggregates(fid, state)

        for r in CORE_RESOURCES:
            res = row["resources"].setdefault(
                r,
                {
                    "production": 0.0,
                    "consumption": 0.0,
                    "stockpile": 0.0,
                    "storage_capacity": DEFAULT_STORAGE.get(r, 5000),
                },
            )
            if "storage_capacity" not in res:
                res["storage_capacity"] = DEFAULT_STORAGE.get(r, 5000)
            res["storage_capacity"] = int(max(100, int(res["storage_capacity"])))

            res["production"] = round(
                0.85 * res["production"] + 0.15 * _estimate_production(r, fid, state, total_pop, active_mil, naval),
                2,
            )
            res["consumption"] = round(
                0.8 * res["consumption"] + 0.2 * _estimate_consumption(r, total_pop, active_mil, naval),
                2,
            )

            cap = int(res["storage_capacity"])
            stock = float(res.get("stockpile", 0.0))
            prod = float(res.get("production", 0.0))
            cons = float(res.get("consumption", 0.0))
            new_stock = stock + prod - cons
            unmet = 0.0
            if new_stock < 0:
                unmet = -new_stock
                new_stock = 0.0
            if new_stock > cap:
                new_stock = float(cap)
            dr = 0.0
            if r == "grain":
                dr = float((state.get("siege_grain_drain_by_faction") or {}).get(fid) or 0.0)
                new_stock = new_stock - dr
                if new_stock < 0:
                    unmet += -new_stock
                    new_stock = 0.0
                if new_stock > cap:
                    new_stock = float(cap)

            sev = unmet / max(1.0, cons) if cons > 0 else 0.0
            sev = _clamp(sev, 0.0, 1.0)
            res["stockpile"] = int(round(new_stock))
            row["shortage_effects"][r] = {"severity": round(sev, 4), "unmet_demand": round(unmet, 2)}

            if r == "grain" and dr:
                row["shortage_effects"][r]["siege_drain"] = round(dr, 2)

            handler = _SHORTAGE_HANDLERS.get(r)
            if handler and sev > 0.01:
                handler(fid, sev, state)

        out_rows.append(row)

    state["faction_economy"] = out_rows
    state.setdefault("economic_disruption_price_mult", 1.0)
    from econ_trade_routes import process_economic_trade_routes

    process_economic_trade_routes(state, prev)
    _run_resource_market(state)
    _sync_legacy_faction_resources(state)


def apply_shortage_to_faction_power(state: dict) -> None:
    """Lower military / economic / political axes when iron or gold reserves are critically short."""
    fe_map = {
        r.get("faction_id") or r.get("faction"): r
        for r in state.get("faction_economy", []) or []
        if r.get("faction_id") or r.get("faction")
    }
    for p in state.get("faction_power_state", []) or []:
        fac = p.get("faction")
        if not fac or fac not in fe_map:
            continue
        se = (fe_map[fac].get("shortage_effects") or {})
        s_iron = float((se.get("iron") or {}).get("severity", 0))
        s_gold = float((se.get("gold") or {}).get("severity", 0))
        m = int(p.get("militaryPower", 50))
        e = int(p.get("economicPower", 50))
        pol = int(p.get("politicalInfluence", 50))
        p["militaryPower"] = int(_clamp(m - 2 - 8 * s_iron * SHORTAGE_STRENGTH, 0, 100))
        p["economicPower"] = int(_clamp(e - 1 - 5 * s_gold * SHORTAGE_STRENGTH, 0, 100))
        p["politicalInfluence"] = int(_clamp(pol - 2 * s_gold * SHORTAGE_STRENGTH, 0, 100))


def _sync_legacy_faction_resources(state: dict) -> None:
    """Map abstract stocks to existing 0-100 `faction_resources` food/materials for older logic."""
    econ_by = {r.get("faction_id") or r.get("faction"): r for r in state.get("faction_economy", [])}

    def _apply_row(fac: str, row: dict) -> None:
        if not fac or fac not in econ_by:
            return
        res = econ_by[fac].get("resources", {})
        g = int((res.get("grain") or {}).get("stockpile", 0)) / 80.0
        i = int((res.get("iron") or {}).get("stockpile", 0)) / 100.0
        t = int((res.get("timber") or {}).get("stockpile", 0)) / 90.0
        au = int((res.get("gold") or {}).get("stockpile", 0)) / 60.0
        row["food"] = int(_clamp((g * 0.5 + 50), 0, 100))
        row["materials"] = int(_clamp((i + t) * 0.5 * 0.3 + 50, 0, 100))
        row["gold"] = int(_clamp(au, 0, 100))
        if not row.get("pressure"):
            gsp = (res.get("grain") or {}).get("stockpile", 0) or 0
            row["pressure"] = "stable" if gsp > 20 else "strained"

    fr = state.get("faction_resources")
    if isinstance(fr, dict):
        for fac, row in fr.items():
            if isinstance(row, dict):
                _apply_row(fac, row)
        return
    for row in (fr or []):
        if not isinstance(row, dict):
            continue
        _apply_row(row.get("faction"), row)


def normalize_faction_economy_rows(prev_state: dict, new_state: dict) -> None:
    """Merge AI / prior `faction_economy` with defaults. Skipped after `run_faction_economy_tick` for this tick."""
    if int(new_state.get("tick", 0)) == new_state.get("_economy_engine_tick"):
        return
    prev = prev_state or {}
    prev_by = {
        r.get("faction_id") or r.get("faction"): r
        for r in (prev.get("faction_economy") or [])
        if r.get("faction_id") or r.get("faction")
    }
    inc_by = {
        r.get("faction_id") or r.get("faction"): r
        for r in (new_state.get("faction_economy") or [])
        if r.get("faction_id") or r.get("faction")
    }
    factions = list_faction_ids(new_state)[:20]
    out: List[dict] = []
    for fid in factions:
        if prev_by.get(fid) or inc_by.get(fid):
            base = {**(prev_by.get(fid) or {}), **(inc_by.get(fid) or {}), "faction_id": fid}
        else:
            base = None
        out.append(_default_faction_economy_row(fid, new_state, base))
    new_state["faction_economy"] = out


def build_economy_export(state: dict) -> List[dict]:
    """Output shape requested for APIs / tools — minimal resource keys per spec."""
    out: List[dict] = []
    for row in state.get("faction_economy", []) or []:
        fid = row.get("faction_id") or row.get("faction")
        if not fid:
            continue
        resources: Dict[str, Any] = {}
        for r in CORE_RESOURCES:
            rec = (row.get("resources") or {}).get(r, {})
            resources[r] = {
                "production": rec.get("production", 0),
                "consumption": rec.get("consumption", 0),
                "stockpile": rec.get("stockpile", 0),
                "storage_capacity": int(rec.get("storage_capacity", DEFAULT_STORAGE.get(r, 5000))),
            }
        out.append({"faction_id": fid, "resources": resources})
    return out


def build_market_export(state: dict) -> Dict[str, Any]:
    """Per-tick market snapshot: world prices, spot trades, and inter-faction economic routes."""
    from military_simulation import build_military_export as _build_mil
    from siege_blockade import build_siege_location_export as _siege_loc
    from treaty_system import build_faction_trust_matrix as _trust_mx

    dyn = state.get("dynastic_report") or {}
    if not isinstance(dyn, dict):
        dyn = {"marriages": [], "claims": [], "potential_conflicts": []}
    return {
        "resource_market": state.get("resource_market") or {},
        "siege_warfare": state.get("siege_warfare") or {},
        "active_siege_locations": _siege_loc(state),
        "economic_trade_routes": state.get("economic_trade_routes") or [],
        "economic_route_flows": state.get("economic_route_flows") or {},
        "economic_pressure_decisions": state.get("economic_pressure_decisions") or [],
        "military_faction_decisions": state.get("military_faction_decisions") or [],
        "treaty_tick_outcomes": state.get("treaty_tick_outcomes") or [],
        "treaties": state.get("treaties") or [],
        "diplomatic_standing": state.get("diplomatic_standing") or {},
        "world_treaty_order": state.get("world_treaty_order"),
        "faction_trust": _trust_mx(state),
        "dynastic_legitimacy": state.get("dynastic_legitimacy") or {},
        "dynastic": {
            "marriages": dyn.get("marriages") or [],
            "claims": dyn.get("claims") or [],
            "potential_conflicts": dyn.get("potential_conflicts") or [],
        },
        "family_politics": state.get("family_politics") or {},
        "tick_lifecycle": state.get("tick_lifecycle")
        if isinstance(state.get("tick_lifecycle"), dict)
        else {
            "births": [],
            "deaths": [],
            "marriages": [],
            "succession_events": [],
        },
        "intrigue_actions": list(state.get("intrigue_actions") or []),
        "intrigue_decisions": list(state.get("intrigue_decisions") or []),
        "spy_networks": list(state.get("spy_networks") or []),
        "assassination_reports": list(state.get("assassination_reports") or []),
        "sabotage_reports": list(state.get("sabotage_reports") or []),
        "sabotage_price_stress": float(state.get("sabotage_price_stress") or 0),
        "blackmail_reports": list(state.get("blackmail_reports") or []),
        "active_blackmail_coercion": list(
            state.get("active_blackmail_coercion") or []
        ),
        "counterintelligence_report": (
            dict(state.get("counterintelligence_report"))
            if isinstance(state.get("counterintelligence_report"), dict)
            else {
                "detected_actions": [],
                "exposed_factions": [],
                "penalties": [],
            }
        ),
        "birth_events": list(state.get("birth_events") or []),
        "death_events": list(state.get("death_events") or []),
        "marriage_events": list(state.get("marriage_events") or []),
        "succession_events": list(state.get("succession_events") or []),
        "tributary": (
            state.get("tributary_report")
            if isinstance(state.get("tributary_report"), dict)
            else {"tributaries": [], "payments": [], "tension_level": 0.0}
        ),
        "tributary_resentment": state.get("tributary_resentment") or {},
        "legitimacy": list(state.get("legitimacy_report") or []),
        "ruler_legitimacy_scores": state.get("ruler_legitimacy_scores") or {},
        "diplomatic_faction_decisions": state.get("diplomatic_faction_decisions") or [],
        "factions": [
            {
                "faction_id": (row.get("faction_id") or row.get("faction")),
                "trades": row.get("trades") or [],
            }
            for row in (state.get("faction_economy") or [])
            if row.get("faction_id") or row.get("faction")
        ],
        "military": _build_mil(state),
        "military_attrition": list(state.get("military_attrition") or []),
        "military_supply": list(state.get("military_supply") or []),
    }


__all__ = [
    "CORE_RESOURCES",
    "DEFAULT_STORAGE",
    "BASE_PRICE",
    "ResourceFlow",
    "list_faction_ids",
    "army_manpower_total",
    "normalize_faction_economy_rows",
    "run_faction_economy_tick",
    "apply_shortage_to_faction_power",
    "build_economy_export",
    "build_market_export",
]
