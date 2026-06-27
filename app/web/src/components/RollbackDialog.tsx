import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, RotateCcw, X } from "lucide-react";

interface RollbackDialogProps {
  reason: string;
  canRollback: boolean;
  isPending: boolean;
  onReasonChange: (reason: string) => void;
  onConfirm: () => void;
}

export default function RollbackDialog({
  reason,
  canRollback,
  isPending,
  onReasonChange,
  onConfirm
}: RollbackDialogProps) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          disabled={!canRollback}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 text-sm font-medium text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RotateCcw className="h-4 w-4" />
          Roll back
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 grid w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border border-zinc-800 bg-zinc-950 p-4 shadow-2xl shadow-black/50">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-sm font-semibold text-zinc-100">Roll back loop</Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-zinc-500">
                The selected loop becomes active and later descendants are marked abandoned.
              </Dialog.Description>
            </div>
            <Dialog.Close className="rounded-md p-1 text-zinc-500 hover:bg-zinc-900 hover:text-zinc-100" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <label className="grid gap-2">
            <span className="text-xs font-medium text-zinc-500">Reason</span>
            <textarea
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              className="min-h-24 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-emerald-400"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Dialog.Close className="h-9 rounded-lg border border-zinc-700 px-3 text-sm text-zinc-100 hover:bg-zinc-900">
              Cancel
            </Dialog.Close>
            <button
              type="button"
              onClick={onConfirm}
              disabled={!reason.trim() || isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-amber-300 px-3 text-sm font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Confirm rollback
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
