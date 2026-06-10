# Decisions

Four calls that shaped this tool, with the alternative each one beat.

## 1. Audit decisions only; never judge output quality

Rejected: routing each prompt to the chosen model for real and scoring the answers.

The decision endpoint exists precisely so you can study routing without burning tokens, and it keeps the audit free, fast (60 prompts in seconds), and runnable in CI on every router upgrade. Quality scoring would also smuggle in a much harder problem (who grades the grader?) and turn a crisp gate into a leaderboard. The cost is real and stated everywhere: RP-005 can only say "this deserves review." Whether haiku would actually have botched those refactors is a question this tool cannot see.

## 2. Baseline = the model you asked for, not all-frontier

Rejected: comparing routed cost against "everything goes to opus."

An all-frontier baseline flatters every router; almost any policy looks like savings next to the most expensive possible one. The honest counterfactual for an adopter is the world they are already in: their agent pins one model (here, claude-sonnet-4-6) and the router intercepts that. Against that baseline this artifact costs +52.7% on the corpus, a number that would have looked like a discount against opus. The flattering baseline would have been marketing, not measurement.

## 3. Curated synthetic corpus, plus an importer for your real traffic

Rejected: synthetic-only (and its mirror image, requiring real history).

Synthetic-only is reproducible but answers a generic question; your traffic is not my 60 prompts. Requiring real history would kill the out-of-the-box demo and drag private data into a public artifact. So the corpus ships curated and labeled as synthetic, and `import_claude_history.py --redact` exists for the run that actually matters, yours. The labels stay honest: `expected_tier` is a prior for analysis, and no check in the gate treats it as a grade.

## 4. FAIL is for broken trust; routing disagreements are REVIEW

Rejected: failing the gate when a hard prompt lands on a budget model.

A gate that fails on opinions trains people to ignore it. The heuristics are priors with documented misses, and a cheap-heavy artifact might be exactly what an operator tuned for. So FAIL is reserved for conditions that invalidate the run itself: router unreachable, auth rejected, contract violated (RP-001/RP-002). Everything the tool merely disagrees with becomes a REVIEW finding with the rule evidence attached, and a human spends thirty seconds per flag instead of learning to bypass the gate. The recorded run shows the shape working: verdict REVIEW with two named prompts to look at.
