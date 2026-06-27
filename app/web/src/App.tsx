import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Activity, GitBranch, PlayCircle } from "lucide-react";
import RunConsole from "./components/RunConsole";
import MemoryPage from "./components/MemoryPage";

export default function App() {
  return (
    <div className="min-h-[100dvh] bg-zinc-950 text-zinc-100">
      <AppHeader />
      <main className="mx-auto grid w-full max-w-[1500px] gap-4 px-4 py-4">
        <Routes>
          <Route path="/" element={<RunConsole />} />
          <Route path="/memory/:runId" element={<MemoryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function AppHeader() {
  const location = useLocation();
  const active = location.pathname.startsWith("/memory") ? "memory" : "run";
  return (
    <header className="border-b border-zinc-800 bg-zinc-950/95">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-4">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-lg border border-emerald-400/40 bg-emerald-400/10">
            <Activity className="h-4 w-4 text-emerald-300" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-zinc-50">MaterialHack Agent</div>
            <div className="text-xs text-zinc-500">Protein design workbench</div>
          </div>
        </div>
        <nav className="flex items-center gap-2 text-sm">
          <Link className={navClass(active === "run")} to="/">
            <PlayCircle className="h-4 w-4" />
            Run
          </Link>
          <Link className={navClass(active === "memory")} to={location.pathname.startsWith("/memory") ? location.pathname : "/"}>
            <GitBranch className="h-4 w-4" />
            Memory
          </Link>
        </nav>
      </div>
    </header>
  );
}

function navClass(isActive: boolean) {
  return [
    "inline-flex items-center gap-2 rounded-lg px-3 py-2 transition",
    isActive ? "bg-zinc-800 text-zinc-50" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
  ].join(" ");
}
