import type { ThemeMode } from "./theme";

const OPTIONS: Array<{ id: ThemeMode; label: string }> = [
  { id: "system", label: "系统" },
  { id: "light", label: "浅" },
  { id: "dark", label: "深" },
];

type Props = {
  mode: ThemeMode;
  onChange: (mode: ThemeMode) => void;
};

export function ThemeSwitch({ mode, onChange }: Props) {
  return (
    <div className="theme-switch" role="group" aria-label="主题">
      {OPTIONS.map((option) => (
        <button
          key={option.id}
          type="button"
          className={mode === option.id ? "active" : undefined}
          aria-pressed={mode === option.id}
          onClick={() => onChange(option.id)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
