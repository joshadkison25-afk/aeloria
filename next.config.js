/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  /**
   * Dev-only: Strict Mode double-invokes effects/renders, which is costly for a heavy map UI.
   * Simulation runs in Flask; Next is mostly presentation. Disable locally for smoother dev.
   */
  reactStrictMode: false,
}

module.exports = nextConfig
