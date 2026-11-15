"""Run a queue of installs so that one product failing never stops the others, and report one result per product.

The window shows the list this returns ('Update all' result list) with a Retry failed button that runs the same queue
again for only the failed products (an interrupted download then resumes, see github.GitHubClient.download).
Pure: the installer, progress and cancel hooks are injected, so it is tested without Qt.
"""
from dataclasses import dataclass


@dataclass
class ItemResult:
    repo: str
    name: str
    ok: bool
    message: str
    version: str = None
    staged: bool = False        # verified and waiting for the one administrator step at the end of the batch
    cancelled: bool = False


def run_batch(inst, rows, ext_installed=lambda product: False, progress_for=None, cancel=lambda: False, on_item=None):
    """Install every row in order. Returns [ItemResult] in the same order (plus the elevated batch's final results)."""
    results = {}
    order = []

    def put(r):
        if r.repo not in results:
            order.append(r.repo)
        results[r.repo] = r
        if on_item:
            on_item(r)
    for row in rows:
        p = row.product
        if cancel():
            put(ItemResult(p.repo, p.name, False, "Skipped (stopped).", cancelled=True))
            continue
        try:
            res = inst.install(row, ext_installed=ext_installed(p), progress=progress_for(p.repo) if progress_for else None, cancel=cancel)
            put(ItemResult(p.repo, p.name, True, res["message"], res.get("version"), bool(res.get("staged"))))
        except InterruptedError:
            put(ItemResult(p.repo, p.name, False, "Cancelled.", cancelled=True))
        except Exception as e:                       # one product's failure is its own result, never the batch's
            put(ItemResult(p.repo, p.name, False, "Refused: %s" % (str(e) or e.__class__.__name__)))
    if getattr(inst, "staged", None):
        names = {s.repo: s.name for s in inst.staged}
        for repo, (ok, msg) in inst.finish_batch().items():
            ver = next((r.version for r in [results.get(repo)] if r), None)
            put(ItemResult(repo, names.get(repo, repo), ok, msg, ver if ok else None))
    return [results[k] for k in order]


def failed(results):
    return [r for r in results if not r.ok and not r.cancelled]


def retryable(results):
    """Everything that did not finish: failures and products skipped by Stop."""
    return [r for r in results if not r.ok]


def summary(results):
    ok = sum(1 for r in results if r.ok)
    bad = sum(1 for r in results if not r.ok)
    if not bad:
        return "%d of %d done." % (ok, len(results))
    return "%d done, %d did not finish. The others were not affected." % (ok, bad)
