import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Props = {
  input: string;
  onInputChange: (input: string) => void;
  instructions: string;
  onInstructionsChange: (instructions: string) => void;
};

export function ResponsesPlaygroundInput({
  input,
  onInputChange,
  instructions,
  onInstructionsChange,
}: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="responses-instructions">Instructions</Label>
        <Textarea
          id="responses-instructions"
          value={instructions}
          placeholder="Optional system-level instructions"
          onChange={(event) => onInstructionsChange(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="responses-input">Input</Label>
        <Textarea
          id="responses-input"
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
        />
      </div>
    </div>
  );
}
