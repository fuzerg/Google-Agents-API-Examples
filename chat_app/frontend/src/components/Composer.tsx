import { useState } from "react";

interface Props {
  disabled?: boolean;
  streaming?: boolean;
  placeholder?: string;
  onSend: (text: string) => void;
  onStop?: () => void;
}

export default function Composer({
  disabled,
  streaming,
  placeholder,
  onSend,
  onStop,
}: Props) {
  const [text, setText] = useState("");

  function submit() {
    const t = text.trim();
    if (!t || disabled || streaming) return;
    onSend(t);
    setText("");
  }

  return (
    <div className="border-t border-neutral-800 bg-neutral-950 p-4">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={placeholder ?? "Send a message…"}
          disabled={disabled || streaming}
          className="max-h-40 flex-1 resize-none rounded-xl border border-neutral-700 bg-neutral-900 px-4 py-3 text-sm text-neutral-100 outline-none placeholder:text-neutral-500 focus:border-neutral-500 disabled:opacity-50"
        />
        {streaming ? (
          <button
            onClick={onStop}
            className="rounded-xl bg-neutral-700 px-4 py-3 text-sm font-medium text-white transition hover:bg-neutral-600"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={disabled || !text.trim()}
            className="rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-40"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
