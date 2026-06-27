"""Agentic protein-design workflow — hackathon prototype.

A closed-loop design -> build -> test -> learn pipeline, orchestrated as a
LangGraph cyclic state machine. Nodes strictly alternate between LLM *reasoning*
(the only place an LLM is allowed to decide) and deterministic *compute* (all
stubbed with seeded random numbers for now).

The 4 reasoning nodes call Claude if ANTHROPIC_API_KEY is set, otherwise they
fall back to deterministic placeholder logic so the whole thing runs offline
with one command and no API key.

Run:
    python pipeline.py "design a protein that binds Zn2+ at pH 5 and can polymerize"
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from typing import Optional

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END

# --------------------------------------------------------------------------- #
# Reproducible RNG (seed configurable via SEED env var or 2nd CLI arg)
# --------------------------------------------------------------------------- #
SEED = int(os.environ.get("SEED", "7"))
RNG = random.Random(SEED)

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


# --------------------------------------------------------------------------- #
# State contract — one Pydantic model carried through the graph
# --------------------------------------------------------------------------- #
class DesignState(BaseModel):
    objective: str = ""                       # raw user input
    spec: dict = Field(default_factory=dict)  # compiled design spec
    strategy: str = "scratch"                 # "scratch" | "template"
    template: Optional[dict] = None           # from memory
    template_score: float = 0.0
    candidates: list[dict] = Field(default_factory=list)
    scored: list[dict] = Field(default_factory=list)
    best: Optional[dict] = None
    pseudo_lab_score: float = 0.0
    iteration: int = 0
    max_iterations: int = 4
    target_score: float = 0.8
    history: list[dict] = Field(default_factory=list)  # best score per iteration
    done: bool = False
    verdict: str = ""


# --------------------------------------------------------------------------- #
# LLM helper — call Claude IF a key is set, else return the fallback
# --------------------------------------------------------------------------- #
MODEL = "claude-opus-4-8"


def reason(system: str, user: str, fallback: dict) -> dict:
    """Call Claude and parse JSON into a dict IF ANTHROPIC_API_KEY is set,
    otherwise return `fallback` so the pipeline runs offline.

    Parsing is defensive: strips code fences, tolerates minor noise, and falls
    back on any error.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback

    try:
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return _parse_json(text, fallback)
    except Exception as exc:  # offline-safe: any failure -> fallback
        print(f"  [reason] LLM call failed ({exc}); using fallback")
        return fallback


def _parse_json(text: str, fallback: dict) -> dict:
    """Strip code fences and pull the first JSON object out of `text`."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t.lstrip("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    return fallback


# --------------------------------------------------------------------------- #
# Stub interfaces — replace each with a real skill (one-function change)
# --------------------------------------------------------------------------- #
def memory_retrieve(spec: dict) -> dict:
    """Return a fake template + a random match score in [0, 1].

    # TODO: replace with real skill (vector search over a design memory).
    """
    score = RNG.random()
    template = {
        "id": f"TMPL-{RNG.randint(1000, 9999)}",
        "motif": RNG.choice(["zinc-finger", "EF-hand", "coiled-coil", "beta-barrel"]),
        "length": RNG.randint(40, 120),
    }
    return {"template": template, "match_score": round(score, 3)}


def boltzgen_generate(spec: dict, n: int = 8) -> list[dict]:
    """Return N candidate design bundles.

    A real BoltzGen call returns far more than a sequence: a structure
    (atomic coordinates), per-residue and global confidence (pLDDT, pTM,
    ipTM, PAE), and design metadata (motif/contig, predicted binding-site
    residues, sampling seed). This stub mirrors that shape with random
    values so downstream nodes (screening, scoring) can consume the same
    fields the real model will produce.

    # TODO: replace with real skill (BoltzGen structure-conditioned generation).
    """
    candidates = []
    length = int(spec.get("length", 60))
    target = spec.get("target", "unknown")
    motif = spec.get(
        "template_id",
        RNG.choice(["zinc-finger", "EF-hand", "coiled-coil", "beta-barrel"]),
    )
    for i in range(n):
        seq = "".join(RNG.choice(AMINO_ACIDS) for _ in range(length))
        plddt_per_residue = [round(RNG.uniform(0.35, 0.98), 3) for _ in range(length)]
        mean_plddt = round(sum(plddt_per_residue) / length, 3)
        n_sites = min(RNG.randint(2, 4), length)
        binding_site_residues = sorted(RNG.sample(range(1, length + 1), k=n_sites))
        candidates.append(
            {
                "id": f"cand-{RNG.randint(10000, 99999)}",
                "sequence": seq,
                "chains": [
                    {"chain_id": "A", "role": "designed", "sequence": seq, "length": length}
                ],
                "structure": {
                    "format": "pdb",
                    "num_atoms": length * 8,  # rough heavy-atom count, stand-in for real coords
                },
                "confidence": {
                    "plddt_per_residue": plddt_per_residue,
                    "plddt": mean_plddt,
                    "ptm": round(RNG.uniform(0.3, 0.9), 3),
                    "iptm": round(RNG.uniform(0.3, 0.9), 3) if target != "unknown" else None,
                    "pae_mean": round(RNG.uniform(2.0, 12.0), 2),
                },
                "design_metadata": {
                    "motif": motif,
                    "binding_site_residues": binding_site_residues,
                    "target": target,
                    "sampling_seed": RNG.randint(0, 2**31 - 1),
                },
            }
        )
    return candidates


def screen_score(candidates: list[dict]) -> list[dict]:
    """Score candidates from BoltzGen's own confidence metrics, return sorted desc.

    Composite of global plddt/ptm plus a small bonus for confidently-placed
    binding-site residues (their local pLDDT), so a "good" candidate is one
    BoltzGen is structurally confident about *at the functional site*, not
    just on average.

    # TODO: replace with real skill (in-silico screening / scoring model).
    """
    for c in candidates:
        conf = c["confidence"]
        site_residues = c["design_metadata"]["binding_site_residues"]
        site_plddt = [conf["plddt_per_residue"][r - 1] for r in site_residues]
        site_confidence = sum(site_plddt) / len(site_plddt)
        c["score"] = round(0.4 * conf["plddt"] + 0.3 * conf["ptm"] + 0.3 * site_confidence, 3)
    return sorted(candidates, key=lambda c: c["score"], reverse=True)


def pseudo_lab(candidate: dict, iteration: int) -> dict:
    """Return a random 'real-world' score for the top candidate, with a slight
    upward bias per iteration to mimic optimization converging.

    # TODO: replace with real skill (wet-lab assay / high-fidelity oracle).
    """
    bias = 0.12 * iteration
    score = min(1.0, RNG.uniform(0.3, 0.7) + bias)
    return {"real_score": round(score, 3)}


# --------------------------------------------------------------------------- #
# Graph nodes — alternating (LLM) and (STUB) per the architecture
# --------------------------------------------------------------------------- #
def objective_intake(state: DesignState) -> DesignState:
    """(LLM) Parse the raw objective into a typed DesignSpec.

    The real work here is meant to happen in the LLM call below — objectives
    are free-form text and can name any target/condition/function, not just
    the ones in the demo string. `_heuristic_intake` is only the no-API-key
    fallback, so it's a general-purpose regex extractor rather than a
    lookup for one specific objective.
    """
    fallback = _heuristic_intake(state.objective)
    spec = reason(
        system="You parse a natural-language protein-design objective into a "
        "compact JSON DesignSpec. The objective may name any target "
        "(ion, small molecule, protein, surface, ...), any condition "
        "(pH, temperature, solvent, ...), and any function — do not assume "
        "it matches a known template. Reply with ONLY a JSON object with "
        "keys: target (str), ph (float), functions (list[str]), length (int, "
        "residues; estimate a sensible default if unspecified).\n"
        'Example: "a protein that binds collagen at pH 6.5 and folds into a '
        'beta-barrel" -> {"target": "collagen", "ph": 6.5, "functions": '
        '["bind", "fold"], "length": 80}',
        user=state.objective,
        fallback=fallback,
    )
    state.spec = spec
    print(f"[1] objective_intake (LLM)   -> spec={spec}")
    return state


# Vocabulary for the offline heuristic fallback only — kept broad so it isn't
# tied to any single demo objective. The LLM path above has no such limits.
_KNOWN_TARGETS = [
    "zn2+", "ca2+", "mg2+", "fe2+", "fe3+", "cu2+", "ni2+", "mn2+",
    "atp", "adp", "dna", "rna", "lipid", "collagen", "heparin",
]
_FUNCTION_KEYWORDS = {
    "bind": "bind", "polymeriz": "polymerize", "catalyz": "catalyze",
    "cleave": "cleave", "fold": "fold", "fluoresc": "fluoresce",
    "transport": "transport", "inhibit": "inhibit", "stabiliz": "stabilize",
    "dimeriz": "dimerize", "aggregat": "aggregate", "sens": "sense",
}


def _heuristic_intake(objective: str) -> dict:
    """Best-effort, regex-based objective parser used only when no LLM is
    available. Does not assume which target/condition/function the
    objective names; everything is detected, not hardcoded to one demo.
    """
    text = objective.lower()

    ph_match = re.search(r"ph\s*([\d.]+)", text)
    ph = float(ph_match.group(1)) if ph_match else 7.0

    target = next((t.upper() for t in _KNOWN_TARGETS if t in text), None)
    if target is None:
        bind_match = re.search(r"binds?\s+(?:to\s+)?([a-z0-9+\-]+)", text)
        target = bind_match.group(1).upper() if bind_match else "unknown"

    functions = [v for k, v in _FUNCTION_KEYWORDS.items() if k in text]

    length_match = re.search(r"(\d+)\s*(?:aa|residues?|amino acids?)", text)
    length = int(length_match.group(1)) if length_match else 60

    return {
        "target": target,
        "ph": ph,
        "functions": functions or ["bind"],
        "length": length,
    }


def memory_retrieval(state: DesignState) -> DesignState:
    """(STUB) Return a fake template + random match score."""
    result = memory_retrieve(state.spec)
    state.template = result["template"]
    state.template_score = result["match_score"]
    print(
        f"[2] memory_retrieval (stub)  -> template={state.template['id']} "
        f"match={state.template_score}"
    )
    return state


def route_strategy(state: DesignState) -> DesignState:
    """(LLM/logic) Choose 'template' if match score >= threshold, else 'scratch'."""
    threshold = 0.5
    fallback = {
        "strategy": "template" if state.template_score >= threshold else "scratch"
    }
    decision = reason(
        system="You route a protein-design job. Given a template match score and "
        f"threshold {threshold}, reply with ONLY JSON {{\"strategy\": "
        '"template"|"scratch"}.',
        user=f"match_score={state.template_score}, threshold={threshold}",
        fallback=fallback,
    )
    state.strategy = decision.get("strategy", fallback["strategy"])
    print(f"[3] route_strategy (LLM)     -> strategy={state.strategy}")
    return state


def compile_spec(state: DesignState) -> DesignState:
    """(LLM) Turn objective + optional template into a BoltzGen-style design spec."""
    state.iteration += 1
    base = dict(state.spec)
    if state.strategy == "template" and state.template:
        base["template_id"] = state.template["id"]
        base["length"] = state.template["length"]
    fallback = {**base, "iteration": state.iteration}
    spec = reason(
        system="You compile a BoltzGen-style design-spec dict from an objective and "
        "an optional template. Reply with ONLY a JSON object.",
        user=json.dumps(
            {
                "objective": state.objective,
                "strategy": state.strategy,
                "template": state.template,
                "iteration": state.iteration,
            }
        ),
        fallback=fallback,
    )
    state.spec = spec
    print(
        f"[4] compile_spec (LLM)       -> iteration {state.iteration}, "
        f"len={spec.get('length')}"
    )
    return state


def boltzgen_node(state: DesignState) -> DesignState:
    """(STUB) Return N candidate design bundles (structure + confidence + metadata)."""
    state.candidates = boltzgen_generate(state.spec, n=8)
    avg_plddt = sum(c["confidence"]["plddt"] for c in state.candidates) / len(state.candidates)
    print(
        f"[5] boltzgen_generate (stub) -> {len(state.candidates)} candidates "
        f"(avg plddt={avg_plddt:.3f})"
    )
    return state


def screen_node(state: DesignState) -> DesignState:
    """(STUB) Score candidates, keep top-k."""
    scored = screen_score(state.candidates)
    state.scored = scored[:3]  # keep top-k
    state.best = state.scored[0]
    print(
        f"[6] screen_score (stub)      -> top score={state.best['score']} "
        f"(id={state.best['id']})"
    )
    return state


def pseudo_lab_node(state: DesignState) -> DesignState:
    """(STUB) Real-world score for the top candidate, biased upward by iteration."""
    result = pseudo_lab(state.best, state.iteration)
    state.pseudo_lab_score = result["real_score"]
    state.history.append(
        {"iteration": state.iteration, "best_id": state.best["id"],
         "screen": state.best["score"], "pseudo_lab": state.pseudo_lab_score}
    )
    print(f"[7] pseudo_lab (stub)        -> real_score={state.pseudo_lab_score}")
    return state


def diagnose_replan(state: DesignState) -> DesignState:
    """(LLM) Decide done vs. continue."""
    met = state.pseudo_lab_score >= state.target_score
    exhausted = state.iteration >= state.max_iterations
    fallback = {
        "done": bool(met or exhausted),
        "verdict": "target met" if met else ("max iterations reached" if exhausted
                                             else "continue optimizing"),
    }
    decision = reason(
        system="You decide whether a protein-design loop is done. Reply with ONLY "
        'JSON {"done": bool, "verdict": str}. It is done if the score meets the '
        "target or iterations are exhausted.",
        user=json.dumps(
            {
                "pseudo_lab_score": state.pseudo_lab_score,
                "target_score": state.target_score,
                "iteration": state.iteration,
                "max_iterations": state.max_iterations,
            }
        ),
        fallback=fallback,
    )
    # Guardrail: always stop once iterations are exhausted, regardless of LLM.
    state.done = bool(decision.get("done", fallback["done"])) or exhausted
    state.verdict = decision.get("verdict", fallback["verdict"])
    print(f"[8] diagnose_replan (LLM)    -> done={state.done} verdict='{state.verdict}'")
    return state


def route_after_diagnose(state: DesignState) -> str:
    return "done" if state.done else "continue"


# --------------------------------------------------------------------------- #
# Build the cyclic graph
# --------------------------------------------------------------------------- #
def build_graph():
    g = StateGraph(DesignState)
    g.add_node("objective_intake", objective_intake)
    g.add_node("memory_retrieval", memory_retrieval)
    g.add_node("route_strategy", route_strategy)
    g.add_node("compile_spec", compile_spec)
    g.add_node("boltzgen_generate", boltzgen_node)
    g.add_node("screen_score", screen_node)
    g.add_node("pseudo_lab", pseudo_lab_node)
    g.add_node("diagnose_replan", diagnose_replan)

    g.set_entry_point("objective_intake")
    g.add_edge("objective_intake", "memory_retrieval")
    g.add_edge("memory_retrieval", "route_strategy")
    g.add_edge("route_strategy", "compile_spec")
    g.add_edge("compile_spec", "boltzgen_generate")
    g.add_edge("boltzgen_generate", "screen_score")
    g.add_edge("screen_score", "pseudo_lab")
    g.add_edge("pseudo_lab", "diagnose_replan")
    # Feedback edge: diagnose_replan -> compile_spec (loop) or END
    g.add_conditional_edges(
        "diagnose_replan",
        route_after_diagnose,
        {"continue": "compile_spec", "done": END},
    )
    return g.compile()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
DEFAULT_OBJECTIVE = "design a protein that binds Zn2+ at pH 5 and can polymerize"


def main() -> None:
    objective = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OBJECTIVE
    mode = "Claude" if os.environ.get("ANTHROPIC_API_KEY") else "offline fallback"

    print("=" * 70)
    print("Agentic Protein-Design Workflow")
    print(f"  objective : {objective}")
    print(f"  reasoning : {mode}  |  seed: {SEED}")
    print("=" * 70)

    graph = build_graph()
    init = DesignState(objective=objective)
    # Recursion limit must cover ~7 nodes/iteration over max_iterations + slack.
    final = graph.invoke(init, config={"recursion_limit": 50})
    state = DesignState(**final)

    print("=" * 70)
    print("Per-iteration trace:")
    for h in state.history:
        print(
            f"  iter {h['iteration']}: best={h['best_id']}  "
            f"screen={h['screen']:.3f}  pseudo_lab={h['pseudo_lab']:.3f}"
        )
    print("-" * 70)
    print("Final summary")
    best = state.best
    conf = best["confidence"]
    meta = best["design_metadata"]
    print(f"  best candidate : {best['id']}")
    print(f"  sequence       : {best['sequence'][:40]}...")
    print(f"  plddt / ptm    : {conf['plddt']:.3f} / {conf['ptm']:.3f}  (iptm={conf['iptm']})")
    print(f"  binding site   : residues {meta['binding_site_residues']} (motif={meta['motif']})")
    print(f"  final score    : {state.pseudo_lab_score:.3f}")
    print(f"  iterations     : {state.iteration}")
    print(f"  verdict        : {state.verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
