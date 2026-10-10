import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type FilterValues = {
  endpoint: string;
  status: string;
  since: string;
  until: string;
};

export const EMPTY_FILTERS: FilterValues = {
  endpoint: "",
  status: "",
  since: "",
  until: "",
};

export const ENDPOINTS = ["/v1/chat/completions", "/v1/responses"] as const;

export function toUnixSeconds(local: string): number | undefined {
  if (!local) return undefined;
  const ms = new Date(local).getTime();
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}

export function endpointOf(value: string): (typeof ENDPOINTS)[number] | undefined {
  return ENDPOINTS.find((endpoint) => endpoint === value);
}

type Props = {
  values: FilterValues;
  onChange: (values: FilterValues) => void;
  statusOptions: readonly string[];
};

const SELECT_CLASS =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30";

export function RequestFilters({ values, onChange, statusOptions }: Props) {
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
          {ENDPOINTS.map((endpoint) => (
            <option key={endpoint} value={endpoint}>
              {endpoint}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="filter-status">Status</Label>
        <select
          id="filter-status"
          className={SELECT_CLASS}
          value={values.status}
          onChange={(event) => onChange({ ...values, status: event.target.value })}
        >
          <option value="">All statuses</option>
          {statusOptions.map((status) => (
            <option key={status} value={status}>
              {status}
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
      <Button type="button" variant="outline" onClick={() => onChange(EMPTY_FILTERS)}>
        Clear filters
      </Button>
    </form>
  );
}
