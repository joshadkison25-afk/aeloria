'use client';

import { useState } from 'react';
import { runTick, Event } from '../lib/sim';

const priestPhrasings = [
  'My lord...',
  'Hear this, faithful one...',
  'The visions reveal...',
  'In the shadows, I see...',
];

function getPriestPhrase(): string {
  return priestPhrasings[Math.floor(Math.random() * priestPhrasings.length)];
}

export default function Home() {
  const [currentEvent, setCurrentEvent] = useState<Event | null>(null);

  const handleAdvanceTime = () => {
    const event = runTick();
    setCurrentEvent(event);
  };

  return (
    <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-8">
      <h1 className="text-6xl font-bold mb-8 text-gray-200">AELORIA</h1>

      <div className="max-w-2xl w-full bg-gray-900 p-6 rounded-lg shadow-lg">
        <div className="text-lg mb-4">The Priest speaks:</div>
        <div className="text-gray-300 italic">
          {currentEvent ? (
            <>
              {getPriestPhrase()} {currentEvent.text}
            </>
          ) : (
            'The world awaits your command...'
          )}
        </div>
      </div>

      <button
        onClick={handleAdvanceTime}
        className="mt-8 px-6 py-3 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
      >
        Advance Time
      </button>
    </div>
  );
}