import type { RequestFilters } from "@/api/observability";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type FilterValues = {
  endpoint: string;
  errorsOnly: boolean;
  since: string;
  until: string;
};

export const EMPTY_FILTERS: FilterValues = {
  endpoint: "",
  errorsOnly: false,
  since: "",
  until: "",
};

const DEFAULT_ENDPOINTS = ["/v1/chat/completions"];

function toUnixSeconds(local: string): number | undefined {
  if (!local) return undefined;
  const ms = new Date(local).getTime();
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}

export function toRequestFilters(values: FilterValues): RequestFilters {
  return {
    endpoint: values.endpoint || undefined,
    outcome: values.errorsOnly ? ["error"] : undefined,
    since: toUnixSeconds(values.since),
    until: toUnixSeconds(values.until),
  };
}

type Props = {
  values: FilterValues;
  onChange: (values: FilterValues) => void;
  knownEndpoints: string[];
};

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30";

export function ObservabilityFilters({ values, onChange, knownEndpoints }: Props) {
  const endpoints = [
    ...new Set([
      ...DEFAULT_ENDPOINTS,
      ...knownEndpoints,
      ...(values.endpoint ? [values.endpoint] : []),
    ]),
  ];

  return (
    <form
      aria-label="Filter requests"
      className="flex flex-wrap items-end gap-4"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-endpoint">Endpoint</Label>
        <select
          id="filter-endpoint"
          className={SELECT_CLASS}
          value={values.endpoint}
          onChange={(event) => onChange({ ...values, endpoint: event.target.value })}
        >
          <option value="">All endpoints</option>
          {endpoints.map((endpoint) => (
            <option key={endpoint} value={endpoint}>
              {endpoint}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-since">Since</Label>
        <Input
          id="filter-since"
          type="datetime-local"
          value={values.since}
          onChange={(event) => onChange({ ...values, since: event.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-until">Until</Label>
        <Input
          id="filter-until"
          type="datetime-local"
          value={values.until}
          onChange={(event) => onChange({ ...values, until: event.target.value })}
        />
      </div>
      <div className="flex h-8 items-center gap-2">
        <input
          id="filter-errors-only"
          type="checkbox"
          checked={values.errorsOnly}
          onChange={(event) =>
            onChange({ ...values, errorsOnly: event.target.checked })
          }
        />
        <Label htmlFor="filter-errors-only">Errors only</Label>
      </div>
    </form>
  );
}
