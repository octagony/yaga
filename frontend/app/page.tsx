'use client'

import { useState } from "react";

export default function Home() {
  const [query, setQuery] = useState('cyberpunk 2077');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError('');
    setResults(null);

    try {

      const apiUrl = 'http://localhost:8000';
      const response = await fetch(`${apiUrl}/api/search?query=${encodeURIComponent(query)}`);
      
      if (!response.ok) throw new Error('Ошибка при запросе к серверу');
      
      const data = await response.json();
      setResults(data);
    } catch (err) {
      setError('Не удалось загрузить данные. Проверьте, запущен ли backend.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-8 max-w-5xl mx-auto">
      <header className="mb-10 text-center">
        <h1 className="text-4xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent mb-2">
          YAGA Aggregator
        </h1>
        <p className="text-slate-400">Сравнение цен на игровые ключи и аккаунты</p>
      </header>

      <form onSubmit={handleSearch} className="flex gap-2 mb-8 max-w-2xl mx-auto">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Например: cyberpunk 2077"
          className="flex-1 px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition"
        >
          {loading ? 'Ищем...' : 'Найти'}
        </button>
      </form>

      {error && <div className="text-red-400 text-center mb-6">{error}</div>}

      {results && (
        <div className="space-y-8">
          {results.cache?.hit && (
            <div className="text-center text-sm text-emerald-400 bg-emerald-900/30 py-2 rounded-lg border border-emerald-800">
              ⚡ Данные загружены из кэша (Обновлено: {new Date(results.cache.cached_at).toLocaleTimeString()})
            </div>
          )}

          {results.matched_groups.map((group, idx) => (
            <div key={idx} className="bg-slate-800/50 border border-slate-700 rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white mb-4">{group.base_title}</h2>
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {group.offers.map((offer, i) => (
                  <div
                    key={i}
                    className={`relative p-4 rounded-lg border transition hover:scale-[1.02] ${
                      offer.is_cheapest
                        ? 'bg-emerald-900/20 border-emerald-500/50'
                        : 'bg-slate-800 border-slate-700'
                    }`}
                  >
                    {offer.is_cheapest && (
                      <span className="absolute -top-3 left-3 bg-emerald-500 text-slate-900 text-xs font-bold px-2 py-1 rounded-full">
                        🥇 ЛУЧШАЯ ЦЕНА
                      </span>
                    )}
                    <div className="flex justify-between items-start mb-2">
                      <span className={`text-sm font-bold ${
                        offer.source.includes('Plati') ? 'text-green-400' : 
                        offer.source.includes('Playerok') ? 'text-blue-400' : 'text-orange-400'
                      }`}>
                        {offer.source}
                      </span>
                      <span className="text-xl font-bold text-white">{offer.price}</span>
                    </div>
                    <p className="text-sm text-slate-400 mb-4 line-clamp-2">{offer.title}</p>
                    <a
                      href={offer.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block w-full text-center py-2 bg-slate-700 hover:bg-slate-600 rounded-md text-sm font-medium transition"
                    >
                      Перейти к товару
                    </a>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {results.matched_groups.length === 0 && (
            <p className="text-center text-slate-500">Совпадений для сравнения не найдено.</p>
          )}
        </div>
      )}
    </div>
  );
}
