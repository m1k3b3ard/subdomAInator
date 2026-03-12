#!/usr/bin/env python3
"""
SUBENUM — Subdomain Enumeration Pipeline
Automated recon pipeline combining passive discovery, active bruteforcing,
permutation generation, and multi-epoch validation.

No external Python dependencies — stdlib only.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ── ANSI Colors & Symbols ──────────────────────────────────────────────────

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    BG_RED  = "\033[41m"
    BG_GREEN = "\033[42m"


SYM_OK    = f"{C.GREEN}✓{C.RESET}"
SYM_FAIL  = f"{C.RED}✗{C.RESET}"
SYM_RUN   = f"{C.CYAN}►{C.RESET}"
SYM_DOWN  = f"{C.BLUE}↓{C.RESET}"
SYM_MERGE = f"{C.MAGENTA}⊕{C.RESET}"
SYM_SKIP  = f"{C.YELLOW}⏭{C.RESET}"
SYM_WARN  = f"{C.YELLOW}⚠{C.RESET}"
SYM_INFO  = f"{C.BLUE}ℹ{C.RESET}"


# ── Utility Functions ──────────────────────────────────────────────────────

def fmt_num(n: int) -> str:
    return f"{n:,}"


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def count_lines(filepath: str) -> int:
    try:
        with open(filepath, "r") as f:
            return sum(1 for line in f if line.strip())
    except FileNotFoundError:
        return 0


def read_lines_set(filepath: str) -> set:
    try:
        with open(filepath, "r") as f:
            return {line.strip().lower() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def write_lines(filepath: str, lines) -> int:
    sorted_lines = sorted(lines)
    with open(filepath, "w") as f:
        for line in sorted_lines:
            f.write(line + "\n")
    return len(sorted_lines)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def tool_exists(name: str) -> bool:
    return shutil.which(name) is not None


def phase_banner(phase_num: int, total: int, title: str):
    line = f"━━━ Phase {phase_num}/{total}: {title} "
    line += "━" * max(0, 60 - len(line) + len(C.BOLD) + len(C.CYAN) + len(C.RESET))
    print(f"\n{C.BOLD}{C.CYAN}{line}{C.RESET}")


def step_start(symbol: str, msg: str):
    print(f"  {symbol} {msg}", end="", flush=True)


def step_end(msg: str = ""):
    if msg:
        print(f" {msg}")
    else:
        print()


def log_detail(msg: str):
    print(f"      {C.DIM}{msg}{C.RESET}")


def log_result(msg: str):
    print(f"  {SYM_OK} {C.GREEN}{msg}{C.RESET}")


def log_warn(msg: str):
    print(f"  {SYM_WARN} {C.YELLOW}{msg}{C.RESET}")


def log_error(msg: str):
    print(f"  {SYM_FAIL} {C.RED}{msg}{C.RESET}")


def log_skip(msg: str):
    print(f"  {SYM_SKIP} {C.YELLOW}{msg}{C.RESET}")


# ── Logger ─────────────────────────────────────────────────────────────────

class FileLogger:
    def __init__(self, log_path: str):
        ensure_dir(os.path.dirname(log_path))
        self.f = open(log_path, "a")
        self.log(f"Session started: {datetime.now().isoformat()}")

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.f.write(f"[{ts}] {msg}\n")
        self.f.flush()

    def close(self):
        self.log("Session ended")
        self.f.close()


# ── State / Resume ─────────────────────────────────────────────────────────

class State:
    def __init__(self, state_path: str):
        self.path = state_path
        self.data = {"phases_completed": [], "current_phase": 0}
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                self.data = json.load(f)

    def is_done(self, phase: int) -> bool:
        return phase in self.data.get("phases_completed", [])

    def mark_start(self, phase: int):
        self.data["current_phase"] = phase
        self._save()

    def mark_done(self, phase: int):
        if phase not in self.data["phases_completed"]:
            self.data["phases_completed"].append(phase)
        self.data["current_phase"] = phase + 1
        self._save()

    def set_meta(self, key: str, value):
        self.data[key] = value
        self._save()

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)


# ── Tool Runner ────────────────────────────────────────────────────────────

def run_tool(cmd: list, label: str, logger: FileLogger, timeout: int = 0) -> tuple:
    """Run an external tool, stream output in real-time, return (success, elapsed_seconds)."""
    cmd_str = " ".join(cmd)
    logger.log(f"CMD: {cmd_str}")

    step_start(SYM_RUN, f"Running {C.BOLD}{label}{C.RESET}...")
    print()

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        line_count = 0
        last_print = time.time()
        for line in proc.stdout:
            stripped = line.rstrip()
            line_count += 1
            now = time.time()
            # Print every line but throttle dense output (show every 50th after first 20)
            if line_count <= 20 or line_count % 50 == 0 or (now - last_print) > 2.0:
                elapsed = fmt_duration(now - t0)
                # Truncate long lines
                display = stripped[:120] + ("..." if len(stripped) > 120 else "")
                print(f"      {C.DIM}[{elapsed}]{C.RESET} {display}")
                last_print = now

        proc.wait(timeout=timeout if timeout > 0 else None)
        elapsed = time.time() - t0
        success = proc.returncode == 0

        if success:
            logger.log(f"OK: {label} ({fmt_duration(elapsed)}, {line_count} output lines)")
        else:
            logger.log(f"FAIL: {label} exit code {proc.returncode}")
            log_warn(f"{label} exited with code {proc.returncode}")

        return success, elapsed

    except FileNotFoundError:
        elapsed = time.time() - t0
        log_error(f"{label}: command not found — is it installed?")
        logger.log(f"ERROR: {label} not found")
        return False, elapsed
    except subprocess.TimeoutExpired:
        proc.kill()
        elapsed = time.time() - t0
        log_error(f"{label}: timed out after {fmt_duration(elapsed)}")
        logger.log(f"TIMEOUT: {label}")
        return False, elapsed
    except Exception as e:
        elapsed = time.time() - t0
        log_error(f"{label}: {e}")
        logger.log(f"ERROR: {label}: {e}")
        return False, elapsed


# ── Pipeline Phases ────────────────────────────────────────────────────────

TOTAL_PHASES = 8


def phase1_prep(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Download resolvers and merge wordlists."""
    phase = 1
    phase_banner(phase, TOTAL_PHASES, "PREP")

    if state.is_done(phase):
        log_skip("Phase 1 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    prep_dir = paths["phase1"]
    ensure_dir(prep_dir)
    resolvers_path = os.path.join(prep_dir, "resolvers.txt")
    merged_path = os.path.join(prep_dir, "merged_wordlist.txt")

    # Download resolvers
    url = cfg.get("resolvers_url", "https://raw.githubusercontent.com/trickest/resolvers/main/resolvers.txt")
    step_start(SYM_DOWN, f"Downloading resolvers from {C.DIM}{url}{C.RESET}...")
    print()
    ok, _ = run_tool(["curl", "-L", "-s", "-o", resolvers_path, url], "curl (resolvers)", logger, timeout=120)
    if ok:
        rc = count_lines(resolvers_path)
        log_result(f"Downloaded {fmt_num(rc)} resolvers")
    else:
        log_error("Failed to download resolvers — check URL or network")
        # Try to use existing resolvers
        if os.path.exists(cfg.get("resolvers_fallback", "")):
            shutil.copy(cfg["resolvers_fallback"], resolvers_path)
            log_warn(f"Using fallback resolvers: {cfg['resolvers_fallback']}")

    # Merge wordlists
    step_start(SYM_MERGE, "Merging wordlists...")
    print()

    wordlists = cfg.get("wordlists", [])
    if not wordlists:
        log_error("No wordlists specified!")
        return

    all_words = set()
    per_file_counts = {}
    for wl in wordlists:
        wl_path = os.path.abspath(wl)
        if not os.path.exists(wl_path):
            log_warn(f"Wordlist not found: {wl}")
            continue
        words = read_lines_set(wl_path)
        per_file_counts[os.path.basename(wl)] = len(words)
        log_detail(f"{os.path.basename(wl)}: {fmt_num(len(words))} words")
        all_words.update(words)

    total_raw = sum(per_file_counts.values())
    dupes = total_raw - len(all_words)
    log_detail(f"Duplicates removed: {fmt_num(dupes)}")

    count = write_lines(merged_path, all_words)
    log_result(f"Final merged wordlist: {fmt_num(count)} unique words → {os.path.basename(merged_path)}")

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 1 complete ({fmt_duration(elapsed)})")


def phase2_passive(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Passive subdomain enumeration: amass + assetfinder."""
    phase = 2
    phase_banner(phase, TOTAL_PHASES, "PASSIVE ENUMERATION")

    if state.is_done(phase):
        log_skip("Phase 2 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    passive_dir = paths["phase2"]
    ensure_dir(passive_dir)
    domain = cfg["domain"]

    subfinder_out = os.path.join(passive_dir, "subfinder.txt")
    assetfinder_out = os.path.join(passive_dir, "assetfinder.txt")

    # Subfinder
    if tool_exists("subfinder"):
        run_tool(
            ["subfinder", "-d", domain, "-all", "-o", subfinder_out],
            "subfinder",
            logger,
            timeout=cfg.get("subfinder_timeout", 600),
        )
        sc = count_lines(subfinder_out)
        if sc == 0:
            log_warn("subfinder found 0 subdomains (configure API keys in ~/.config/subfinder/provider-config.yaml)")
        else:
            log_result(f"subfinder found {fmt_num(sc)} subdomains")
    else:
        log_warn("subfinder not found — skipping")
        open(subfinder_out, "w").close()

    # Assetfinder
    if tool_exists("assetfinder"):
        # assetfinder writes to stdout, so we capture it
        step_start(SYM_RUN, f"Running {C.BOLD}assetfinder{C.RESET}...")
        print()
        at0 = time.time()
        try:
            result = subprocess.run(
                ["assetfinder", "--subs-only", domain],
                capture_output=True, text=True, timeout=300,
            )
            with open(assetfinder_out, "w") as f:
                f.write(result.stdout)
            afc_raw = count_lines(assetfinder_out)
            afc_unique = len(read_lines_set(assetfinder_out))
            log_result(f"assetfinder found {fmt_num(afc_unique)} unique subdomains ({fmt_num(afc_raw)} raw, {fmt_num(afc_raw - afc_unique)} duplicates removed) ({fmt_duration(time.time() - at0)})")
        except FileNotFoundError:
            log_warn("assetfinder not found — skipping")
            open(assetfinder_out, "w").close()
        except subprocess.TimeoutExpired:
            log_warn("assetfinder timed out")
            open(assetfinder_out, "w").close()
    else:
        log_warn("assetfinder not found — skipping")
        open(assetfinder_out, "w").close()

    # Summary
    total = read_lines_set(subfinder_out) | read_lines_set(assetfinder_out)
    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 2 complete — {fmt_num(len(total))} unique passive subdomains ({fmt_duration(elapsed)})")


def phase3_active(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Active bruteforcing: puredns + shuffledns."""
    phase = 3
    phase_banner(phase, TOTAL_PHASES, "ACTIVE BRUTEFORCE")

    if state.is_done(phase):
        log_skip("Phase 3 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    active_dir = paths["phase3"]
    ensure_dir(active_dir)
    domain = cfg["domain"]
    wordlist = os.path.join(paths["phase1"], "merged_wordlist.txt")
    resolvers = os.path.join(paths["phase1"], "resolvers.txt")

    puredns_out = os.path.join(active_dir, "puredns.txt")
    shuffledns_out = os.path.join(active_dir, "shuffledns.txt")

    if not os.path.exists(wordlist):
        log_error(f"Merged wordlist not found: {wordlist}")
        return
    if not os.path.exists(resolvers):
        log_error(f"Resolvers not found: {resolvers}")
        return

    log_detail(f"Wordlist: {fmt_num(count_lines(wordlist))} words")
    log_detail(f"Resolvers: {fmt_num(count_lines(resolvers))}")

    # Puredns bruteforce
    if tool_exists("puredns"):
        run_tool(
            ["puredns", "bruteforce", wordlist, domain,
             "-r", resolvers, "-w", puredns_out],
            "puredns bruteforce",
            logger,
        )
        pc = count_lines(puredns_out)
        log_result(f"puredns found {fmt_num(pc)} subdomains")
    else:
        log_warn("puredns not found — skipping")
        open(puredns_out, "w").close()

    # Shuffledns bruteforce
    if tool_exists("shuffledns"):
        run_tool(
            ["shuffledns", "-d", domain, "-w", wordlist,
             "-r", resolvers, "-mode", "bruteforce", "-o", shuffledns_out],
            "shuffledns bruteforce",
            logger,
        )
        sc = count_lines(shuffledns_out)
        log_result(f"shuffledns found {fmt_num(sc)} subdomains")
    else:
        log_warn("shuffledns not found — skipping")
        open(shuffledns_out, "w").close()

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 3 complete ({fmt_duration(elapsed)})")


def phase4_merge_round1(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Merge passive + active results."""
    phase = 4
    phase_banner(phase, TOTAL_PHASES, "MERGE ROUND 1")

    if state.is_done(phase):
        log_skip("Phase 4 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    sources = {
        "subfinder":   os.path.join(paths["phase2"], "subfinder.txt"),
        "assetfinder": os.path.join(paths["phase2"], "assetfinder.txt"),
        "puredns":     os.path.join(paths["phase3"], "puredns.txt"),
        "shuffledns":  os.path.join(paths["phase3"], "shuffledns.txt"),
    }

    all_subs = set()
    for name, fpath in sources.items():
        subs = read_lines_set(fpath)
        log_detail(f"{name}: {fmt_num(len(subs))} subdomains")
        all_subs.update(subs)

    merged_path = paths["phase4"]
    count = write_lines(merged_path, all_subs)
    logger.log(f"Round 1 merge: {count} unique subdomains")

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 4 complete — {fmt_num(count)} unique subdomains merged ({fmt_duration(elapsed)})")


def phase5_permutation(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Generate permutations with alterx and resolve them."""
    phase = 5
    phase_banner(phase, TOTAL_PHASES, "PERMUTATION (alterx)")

    if state.is_done(phase):
        log_skip("Phase 5 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    perm_dir = paths["phase5"]
    ensure_dir(perm_dir)
    resolvers = os.path.join(paths["phase1"], "resolvers.txt")
    input_subs = paths["phase4"]

    alterx_gen = os.path.join(perm_dir, "alterx_generated.txt")
    alterx_resolved = os.path.join(perm_dir, "alterx_resolved.txt")

    input_count = count_lines(input_subs)
    log_detail(f"Input subdomains: {fmt_num(input_count)}")

    if input_count == 0:
        log_warn("No subdomains from Round 1 — skipping permutation")
        open(alterx_gen, "w").close()
        open(alterx_resolved, "w").close()
        state.mark_done(phase)
        return

    # Generate permutations
    if tool_exists("alterx"):
        run_tool(
            ["alterx", "-l", input_subs, "-o", alterx_gen],
            "alterx (generate permutations)",
            logger,
        )
        gen_count = count_lines(alterx_gen)
        log_result(f"alterx generated {fmt_num(gen_count)} permutations")

        if gen_count > 0:
            # Resolve permutations with puredns
            if tool_exists("puredns"):
                run_tool(
                    ["puredns", "resolve", alterx_gen,
                     "-r", resolvers, "-w", alterx_resolved],
                    "puredns (resolve permutations)",
                    logger,
                )
                res_count = count_lines(alterx_resolved)
                log_result(f"Resolved {fmt_num(res_count)} permuted subdomains")
            else:
                log_warn("puredns not found — cannot resolve permutations")
                open(alterx_resolved, "w").close()
        else:
            open(alterx_resolved, "w").close()
    else:
        log_warn("alterx not found — skipping permutation phase")
        open(alterx_gen, "w").close()
        open(alterx_resolved, "w").close()

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 5 complete ({fmt_duration(elapsed)})")


def phase6_merge_all(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Merge all discovered subdomains."""
    phase = 6
    phase_banner(phase, TOTAL_PHASES, "MERGE ALL")

    if state.is_done(phase):
        log_skip("Phase 6 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    round1 = read_lines_set(paths["phase4"])
    permuted = read_lines_set(os.path.join(paths["phase5"], "alterx_resolved.txt"))

    log_detail(f"Round 1 subdomains: {fmt_num(len(round1))}")
    log_detail(f"Permutation resolved: {fmt_num(len(permuted))}")
    new_from_perm = permuted - round1
    log_detail(f"New from permutation: {fmt_num(len(new_from_perm))}")

    all_subs = round1 | permuted
    merged_path = paths["phase6"]
    count = write_lines(merged_path, all_subs)
    logger.log(f"Final merge: {count} unique subdomains")

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 6 complete — {fmt_num(count)} total unique subdomains ({fmt_duration(elapsed)})")


def phase7_validation(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """Validate subdomains with dnsx (2 epochs)."""
    phase = 7
    phase_banner(phase, TOTAL_PHASES, "VALIDATION (dnsx × 2 epochs)")

    if state.is_done(phase):
        log_skip("Phase 7 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    val_dir = paths["phase7"]
    ensure_dir(val_dir)
    resolvers = os.path.join(paths["phase1"], "resolvers.txt")
    input_subs = paths["phase6"]

    epoch1_out = os.path.join(val_dir, "dnsx_epoch1.txt")
    epoch2_out = os.path.join(val_dir, "dnsx_epoch2.txt")
    validated_out = os.path.join(val_dir, "dnsx_validated.txt")

    input_count = count_lines(input_subs)
    log_detail(f"Input subdomains: {fmt_num(input_count)}")

    if not tool_exists("dnsx"):
        log_warn("dnsx not found — copying input as-is")
        shutil.copy(input_subs, validated_out)
        state.mark_done(phase)
        return

    # Epoch 1
    # Helper: extract unique subdomain names from dnsx output
    # dnsx outputs "sub.domain.com [A] [1.2.3.4]" — multiple lines per domain (one per record)
    def extract_subs_from_dnsx(fpath):
        subs = set()
        for line in read_lines_set(fpath):
            parts = line.split()
            if parts:
                subs.add(parts[0])
        return subs

    # Epoch 1
    print(f"\n  {C.BOLD}── Epoch 1/2 ──{C.RESET}")
    run_tool(
        ["dnsx", "-l", input_subs, "-r", resolvers, "-a", "-resp", "-o", epoch1_out],
        "dnsx (epoch 1)",
        logger,
    )
    e1_subs = extract_subs_from_dnsx(epoch1_out)
    log_result(f"Epoch 1: {fmt_num(len(e1_subs))} unique domains alive ({fmt_num(count_lines(epoch1_out))} DNS records)")

    # Epoch 2
    print(f"\n  {C.BOLD}── Epoch 2/2 ──{C.RESET}")
    run_tool(
        ["dnsx", "-l", input_subs, "-r", resolvers, "-a", "-resp", "-o", epoch2_out],
        "dnsx (epoch 2)",
        logger,
    )
    e2_subs = extract_subs_from_dnsx(epoch2_out)
    log_result(f"Epoch 2: {fmt_num(len(e2_subs))} unique domains alive ({fmt_num(count_lines(epoch2_out))} DNS records)")

    union = e1_subs | e2_subs
    count = write_lines(validated_out, union)

    only_e1 = e1_subs - e2_subs
    only_e2 = e2_subs - e1_subs
    if only_e1 or only_e2:
        log_detail(f"Only in epoch 1: {fmt_num(len(only_e1))}, only in epoch 2: {fmt_num(len(only_e2))}")
        log_detail("(This is why we run 2 epochs!)")

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 7 complete — {fmt_num(count)} validated subdomains ({fmt_duration(elapsed)})")


def phase8_httpx(cfg: dict, paths: dict, state: State, logger: FileLogger):
    """HTTP probe with httpx (2 epochs)."""
    phase = 8
    phase_banner(phase, TOTAL_PHASES, "HTTP PROBING (httpx × 2 epochs)")

    if state.is_done(phase):
        log_skip("Phase 8 already complete — skipping (resume mode)")
        return
    state.mark_start(phase)
    t0 = time.time()

    httpx_dir = paths["phase8"]
    ensure_dir(httpx_dir)
    validated_subs = os.path.join(paths["phase7"], "dnsx_validated.txt")

    # If phase 7 was skipped (no dnsx), use phase 6 output
    if not os.path.exists(validated_subs) or count_lines(validated_subs) == 0:
        validated_subs = paths["phase6"]

    epoch1_out = os.path.join(httpx_dir, "httpx_epoch1.txt")
    epoch2_out = os.path.join(httpx_dir, "httpx_epoch2.txt")
    final_out = os.path.join(httpx_dir, "httpx_live_final.txt")

    input_count = count_lines(validated_subs)
    log_detail(f"Input subdomains: {fmt_num(input_count)}")

    if not tool_exists("httpx"):
        log_error("httpx not found — cannot probe HTTP")
        state.mark_done(phase)
        return

    # Epoch 1
    print(f"\n  {C.BOLD}── Epoch 1/2 ──{C.RESET}")
    run_tool(
        ["httpx", "-l", validated_subs, "-title", "-status-code",
         "-tech-detect", "-o", epoch1_out],
        "httpx (epoch 1)",
        logger,
    )
    e1_count = count_lines(epoch1_out)
    log_result(f"Epoch 1: {fmt_num(e1_count)} live hosts")

    # Epoch 2
    print(f"\n  {C.BOLD}── Epoch 2/2 ──{C.RESET}")
    run_tool(
        ["httpx", "-l", validated_subs, "-title", "-status-code",
         "-tech-detect", "-o", epoch2_out],
        "httpx (epoch 2)",
        logger,
    )
    e2_count = count_lines(epoch2_out)
    log_result(f"Epoch 2: {fmt_num(e2_count)} live hosts")

    # Union — httpx output has metadata, so we union by URL (first token)
    def extract_urls(fpath):
        urls = {}
        for line in read_lines_set(fpath):
            parts = line.split()
            if parts:
                urls[parts[0]] = line  # Keep the full line with metadata
        return urls

    e1_urls = extract_urls(epoch1_out)
    e2_urls = extract_urls(epoch2_out)

    # Merge: prefer epoch 2 data (more recent), add epoch 1 unique
    merged = {**e1_urls, **e2_urls}
    with open(final_out, "w") as f:
        for url in sorted(merged.keys()):
            f.write(merged[url] + "\n")

    only_e1 = set(e1_urls.keys()) - set(e2_urls.keys())
    only_e2 = set(e2_urls.keys()) - set(e1_urls.keys())
    if only_e1 or only_e2:
        log_detail(f"Only in epoch 1: {fmt_num(len(only_e1))}, only in epoch 2: {fmt_num(len(only_e2))}")

    # Create clean subdomain list — just bare hostnames, no scheme/status/metadata
    # Placed next to subenum.py for easy access
    clean_out = paths["live_clean"]
    clean_subs = set()
    for url in merged.keys():
        # Strip http:// or https://
        host = url.replace("https://", "").replace("http://", "")
        # Remove any trailing path
        host = host.split("/")[0]
        # Remove port if present
        host = host.split(":")[0]
        clean_subs.add(host)
    clean_count = write_lines(clean_out, clean_subs)
    log_result(f"Clean subdomain list: {fmt_num(clean_count)} hosts → {os.path.basename(clean_out)}")

    elapsed = time.time() - t0
    state.mark_done(phase)
    log_result(f"Phase 8 complete — {fmt_num(len(merged))} live hosts total ({fmt_duration(elapsed)})")


# ── Final Summary ──────────────────────────────────────────────────────────

def print_summary(paths: dict, total_elapsed: float):
    print(f"\n{'═' * 62}")
    print(f"{C.BOLD}{C.GREEN}  PIPELINE COMPLETE{C.RESET}")
    print(f"{'═' * 62}")

    stats = [
        ("Passive subs",    paths["phase4"],                          "round 1 merged"),
        ("Permuted new",    os.path.join(paths["phase5"], "alterx_resolved.txt"), "from alterx"),
        ("Total discovered", paths["phase6"],                         "all merged"),
        ("DNS validated",   os.path.join(paths["phase7"], "dnsx_validated.txt"),  "dnsx confirmed"),
        ("Live HTTP hosts", os.path.join(paths["phase8"], "httpx_live_final.txt"), "httpx confirmed"),
    ]

    for label, fpath, desc in stats:
        c = count_lines(fpath) if os.path.exists(fpath) else 0
        marker = C.GREEN if c > 0 else C.DIM
        print(f"  {marker}{label:.<30} {fmt_num(c):>10}  ({desc}){C.RESET}")

    print(f"\n  {SYM_INFO} Total time: {C.BOLD}{fmt_duration(total_elapsed)}{C.RESET}")
    print(f"  {SYM_INFO} Output dir: {C.BOLD}{os.path.dirname(paths['phase4'])}{C.RESET}")

    final = os.path.join(paths["phase8"], "httpx_live_final.txt")
    if os.path.exists(final) and count_lines(final) > 0:
        print(f"  {C.DIM}Full httpx output → {final}{C.RESET}")

    clean = paths["live_clean"]
    if os.path.exists(clean) and count_lines(clean) > 0:
        print(f"\n  {C.BOLD}{C.CYAN}Clean live subdomains → {os.path.abspath(clean)}{C.RESET}")

    print()


# ── Tool Check ─────────────────────────────────────────────────────────────

def check_tools():
    """Check which tools are available."""
    required = ["curl"]
    optional = ["puredns", "shuffledns", "subfinder", "assetfinder", "alterx", "dnsx", "httpx"]

    print(f"\n{C.BOLD}Tool Check:{C.RESET}")
    all_ok = True

    for tool in required:
        if tool_exists(tool):
            print(f"  {SYM_OK} {tool}")
        else:
            print(f"  {SYM_FAIL} {tool} {C.RED}(REQUIRED){C.RESET}")
            all_ok = False

    for tool in optional:
        if tool_exists(tool):
            print(f"  {SYM_OK} {tool}")
        else:
            print(f"  {SYM_WARN} {tool} {C.YELLOW}(not found — phase using it will be skipped){C.RESET}")

    if not all_ok:
        print(f"\n  {SYM_FAIL} {C.RED}Missing required tools. Install them and retry.{C.RESET}")
        sys.exit(1)

    print()


# ── Config ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "domain": "example.com",
    "wordlists": ["dns_1.txt", "dns_2.txt", "dns_3.txt"],
    "resolvers_url": "https://raw.githubusercontent.com/trickest/resolvers/main/resolvers.txt",
    "output_dir": "./output",
    "subfinder_timeout": 600,
}


def create_default_config(path: str):
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    print(f"{SYM_OK} Default config written to {C.BOLD}{path}{C.RESET}")
    print(f"  Edit it and run: python3 subenum.py -c {path}")


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


# ── Main ───────────────────────────────────────────────────────────────────

def build_paths(base_dir: str) -> dict:
    return {
        "base":    base_dir,
        "logs":    os.path.join(base_dir, "logs"),
        "phase1":  os.path.join(base_dir, "phase1_prep"),
        "phase2":  os.path.join(base_dir, "phase2_passive"),
        "phase3":  os.path.join(base_dir, "phase3_active"),
        "phase4":  os.path.join(base_dir, "phase4_round1_merged.txt"),
        "phase5":  os.path.join(base_dir, "phase5_permutation"),
        "phase6":  os.path.join(base_dir, "phase6_all_merged.txt"),
        "phase7":  os.path.join(base_dir, "phase7_validation"),
        "phase8":    os.path.join(base_dir, "phase8_httpx"),
        "state":     os.path.join(base_dir, "state.json"),
        "live_clean": os.path.join(base_dir, "..", "..", "live_subdomains.txt"),
    }


def print_header(domain: str, resume: bool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = f"{C.YELLOW}RESUME{C.RESET}" if resume else f"{C.GREEN}NEW RUN{C.RESET}"
    print(f"""
{C.BOLD}╔══════════════════════════════════════════════════════════════╗
║  SUBENUM — Subdomain Enumeration Pipeline                    ║
║  Target: {domain:<53}║
║  Started: {now:<52}║
║  Mode: {('RESUME' if resume else 'NEW RUN'):<55}║
╚══════════════════════════════════════════════════════════════╝{C.RESET}""")


def main():
    parser = argparse.ArgumentParser(
        description="SUBENUM — Subdomain Enumeration Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 subenum.py --init                          Create default config
  python3 subenum.py -d trip.com                     Quick run with defaults
  python3 subenum.py -c config.json                  Run with config file
  python3 subenum.py -c config.json --resume         Resume interrupted run
  python3 subenum.py -d trip.com -w a.txt b.txt      Custom wordlists
        """,
    )
    parser.add_argument("--init", action="store_true", help="Create default config.json")
    parser.add_argument("-c", "--config", help="Path to config JSON file")
    parser.add_argument("-d", "--domain", help="Target domain")
    parser.add_argument("-w", "--wordlists", nargs="+", help="Wordlist files")
    parser.add_argument("-r", "--resolvers-url", help="URL to download resolvers")
    parser.add_argument("-o", "--output", help="Output directory")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--check", action="store_true", help="Only check tool availability")

    args = parser.parse_args()

    # --init: create default config
    if args.init:
        create_default_config("config.json")
        return

    # Load config from file or build from CLI args
    if args.config:
        cfg = load_config(args.config)
    else:
        cfg = dict(DEFAULT_CONFIG)

    # CLI overrides
    if args.domain:
        cfg["domain"] = args.domain
    if args.wordlists:
        cfg["wordlists"] = args.wordlists
    if args.resolvers_url:
        cfg["resolvers_url"] = args.resolvers_url
    if args.output:
        cfg["output_dir"] = args.output

    # --check: tool availability only (no domain needed)
    if args.check:
        check_tools()
        return

    if cfg["domain"] == "example.com":
        print(f"{SYM_FAIL} {C.RED}No domain specified. Use -d <domain> or edit config.json{C.RESET}")
        sys.exit(1)

    # Build output paths
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join(cfg.get("output_dir", "./output"), cfg["domain"], date_str)
    paths = build_paths(base_dir)

    # Create dirs
    for key, path in paths.items():
        if key in ("phase4", "phase6", "state"):
            ensure_dir(os.path.dirname(path))
        elif key != "base":
            ensure_dir(path)

    # State
    state = State(paths["state"])
    is_resume = args.resume and os.path.exists(paths["state"])

    if is_resume:
        completed = state.data.get("phases_completed", [])
        print(f"\n{SYM_INFO} Resuming — phases already done: {completed}")
    else:
        # Fresh run — reset state
        state = State.__new__(State)
        state.path = paths["state"]
        state.data = {"phases_completed": [], "current_phase": 0,
                      "domain": cfg["domain"], "started_at": datetime.now().isoformat()}
        state._save()

    # Header
    print_header(cfg["domain"], is_resume)
    check_tools()

    # Logger
    log_path = os.path.join(paths["logs"], "subenum.log")
    logger = FileLogger(log_path)
    logger.log(f"Domain: {cfg['domain']}")
    logger.log(f"Wordlists: {cfg['wordlists']}")
    logger.log(f"Resume: {is_resume}")

    total_t0 = time.time()

    # Run pipeline
    try:
        phase1_prep(cfg, paths, state, logger)
        phase2_passive(cfg, paths, state, logger)
        phase3_active(cfg, paths, state, logger)
        phase4_merge_round1(cfg, paths, state, logger)
        phase5_permutation(cfg, paths, state, logger)
        phase6_merge_all(cfg, paths, state, logger)
        phase7_validation(cfg, paths, state, logger)
        phase8_httpx(cfg, paths, state, logger)

        total_elapsed = time.time() - total_t0
        print_summary(paths, total_elapsed)

    except KeyboardInterrupt:
        elapsed = time.time() - total_t0
        print(f"\n\n{SYM_WARN} {C.YELLOW}Interrupted after {fmt_duration(elapsed)}{C.RESET}")
        print(f"  {SYM_INFO} Resume with: python3 subenum.py -c <config> --resume")
        logger.log(f"INTERRUPTED after {fmt_duration(elapsed)}")
    except Exception as e:
        logger.log(f"FATAL: {e}")
        print(f"\n{SYM_FAIL} {C.RED}Fatal error: {e}{C.RESET}")
        print(f"  {SYM_INFO} Check log: {log_path}")
        raise
    finally:
        logger.close()


if __name__ == "__main__":
    main()
