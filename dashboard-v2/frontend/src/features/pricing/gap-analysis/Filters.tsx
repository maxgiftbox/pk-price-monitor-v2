import type { FilterResponse } from '../../../types/pricing';

type Props = {
  data?: FilterResponse;
  params: URLSearchParams;
  set: (next: URLSearchParams) => void;
};

const config = [
  ['country', 'Country', 'countries'],
  ['brand', 'Brand', 'brands'],
  ['sku', 'SKU', 'skus'],
  ['memory', 'Memory', 'memories'],
  ['competitor', 'Competitor', 'competitors'],
  ['alert', 'Alert', 'alerts'],
] as const;

function selectionLabel(values: string[]) {
  if (values.length === 0) return 'All';
  if (values.length === 1) return values[0];
  return `${values.length} selected`;
}

export function Filters({ data, params, set }: Props) {
  const options = {
    ...data?.options,
    alerts: ['Red', 'Orange', 'Green'],
  } as Record<string, string[] | object | undefined>;

  function changeMany(key: string, values: string[]) {
    const next = new URLSearchParams(params);
    next.delete(key);
    values.forEach((value) => next.append(key, value));
    next.delete('page');

    if (key === 'country') {
      next.delete('brand');
      next.delete('sku');
      next.delete('memory');
    }
    if (key === 'brand') {
      next.delete('sku');
      next.delete('memory');
    }
    if (key === 'sku') next.delete('memory');

    set(next);
  }

  function changeDate(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete('page');
    set(next);
  }

  return (
    <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
      {config.map(([key, label, list]) => {
        const available = (options[list] as string[]) ?? [];
        const selected = params.getAll(key);

        return (
          <div className="text-xs font-semibold text-slate-600" key={key}>
            <span>{label}</span>
            <details className="group relative mt-1">
              <summary
                aria-label={`${label}: ${selectionLabel(selected)}`}
                className="flex cursor-pointer list-none items-center justify-between rounded-lg border bg-white px-3 py-2 text-sm font-normal text-slate-800 marker:hidden"
              >
                <span className="truncate">{selectionLabel(selected)}</span>
                <span className="ml-2 text-slate-400 group-open:rotate-180">⌄</span>
              </summary>
              <div className="absolute z-50 mt-1 max-h-64 w-full min-w-48 overflow-y-auto rounded-lg border bg-white p-2 shadow-lg">
                <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-2 font-normal hover:bg-slate-50">
                  <input
                    aria-label={`All ${label}`}
                    checked={selected.length === 0}
                    onChange={() => changeMany(key, [])}
                    type="checkbox"
                  />
                  All
                </label>
                {available.map((value) => (
                  <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-2 font-normal hover:bg-slate-50" key={value}>
                    <input
                      checked={selected.includes(value)}
                      onChange={(event) => {
                        const next = event.target.checked
                          ? [...selected, value]
                          : selected.filter((item) => item !== value);
                        changeMany(key, next);
                      }}
                      type="checkbox"
                    />
                    <span>{value}</span>
                  </label>
                ))}
              </div>
            </details>
          </div>
        );
      })}

      {[
        ['dateFrom', 'From'],
        ['dateTo', 'To'],
      ].map(([key, label]) => (
        <label className="text-xs font-semibold text-slate-600" key={key}>
          {label}
          <input
            aria-label={label}
            className="mt-1 w-full rounded-lg border px-3 py-2 text-sm font-normal"
            max={data?.options.dateRange.max ?? undefined}
            min={data?.options.dateRange.min ?? undefined}
            onChange={(event) => changeDate(key, event.target.value)}
            type="date"
            value={params.get(key) ?? ''}
          />
        </label>
      ))}
    </div>
  );
}
