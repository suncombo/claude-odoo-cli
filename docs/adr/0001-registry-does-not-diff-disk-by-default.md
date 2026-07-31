# `registry modules` does not compare against disk by default

`modules` reports what Odoo's registry knows. Comparing that against the module
directories on disk is opt-in, behind `--addons-path`.

The two sources genuinely disagree. Measured on one Odoo 13 database and its
addons checkout: the registry knew 1,337 modules, the tree held 1,286, and they
diverged in both directions — 123 modules the registry knew with no directory in
that tree, 72 directories the registry had never scanned. Two of the 123 were in
state `installed`: the database believed code was running that was not there.

That divergence is exactly what a provenance tool should surface, so the case for
diffing by default is strong. It was rejected anyway, because the comparison is
only meaningful against the tree the database actually runs — and by default we
cannot know that we have it. Deployments pin an image, not a working copy, so
diffing a production database against a local checkout reports the difference
between two versions and labels it drift. A tool whose whole purpose is telling
you which modules are really live cannot afford an answer that is confidently
wrong whenever the caller's checkout is merely on a different commit.

Requiring `--addons-path` makes the caller name the tree, which is the moment
they can notice it is the wrong one. A path that does not exist is an error
rather than an empty scan, for the same reason: `rglob` over a typo yields
nothing, which would classify every installed module as running without code.

## Considered Options

- **Diff on a discovered addons path by default** — rejected: the discovery
  cannot distinguish "the tree this database runs" from "a tree", and the failure
  is silent and alarming rather than obvious.
- **No disk comparison at all** — rejected: the two `installed` modules with no
  code were found this way, and nothing else in the toolchain reports them.

## Consequences

`modules` alone can never answer "is anything installed whose code is missing".
That question requires the caller to supply the tree, which is the constraint
that makes the answer trustworthy.

Hidden directories are skipped during the scan: git worktrees are commonly parked
inside the addons tree (`.claude/worktrees/<name>/`), and counting their copies
would report a module that exists only in an unfinished branch as code that is on
disk but not installed.
