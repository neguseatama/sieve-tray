"""Vendored sieve_crowd/ must byte-match the pinned upstream release.

The pins below are refreshed only when the vendored package is
intentionally re-vendored from the published Sieve Crowd repository
(tag v0.2.0). Every vendored file is re-checked against these pins on
each test run, so silent drift between the two fails the build and a
human reviews the diff (intentional update vs missed sync).
"""

import hashlib
import pathlib

VENDORED = pathlib.Path(__file__).resolve().parent.parent / "sieve_crowd"
PINNED_SHA256 = {
    "__init__.py": "51b67528d2fdf8e33d2a540c1840c777f358064719e7316157be9bc4522f7f29",
    "__main__.py": "935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d",
    "cli.py": "ac923ec314183375cd5e59e79b2e3eb3a2d924436b997a1bbf01a3725cb2c6ff",
    "config.py": "d7930a8c1727bef209808485aef08f727e54a669272a1407a88f12e441e50c4a",
    "csvio.py": "a44bc5be874c6dbbb26b4c5d852cc424ba826614233ebea1c3a5e2c8b0b538fa",
    "engine.py": "9d3922fd16041bdf67d599453b93aad51597c72043ada345b7185e8784eeb031",
    "generalize.py": "383201fe9686ce756531cc716d07b783a7fe697e3f40153ae040bbb3f5d12f5b",
    "hints.py": "a0d79c844380a2ac0d21900be0ad7d7d65a64f064266516a5674cf23ff8271d3",
    "jsonio.py": "60a5b1ea05137ad3f6ab710eb11879b19b528658e95452db7c15f98cc8891cd9",
    "measure.py": "18e00c4548d906aa91134a99ca5581aed5951f5ad2e1eefedac154efbf064d65",
    "model.py": "5bd109dfd9183e59bd66abc4257b47776870d1e18472dee3a33e064173fde496",
    "prng.py": "8e8eefe63cb711c72e5bd2da43ea198245361692796a1529b402d72bc5728594",
    "pseudonym.py": "e58d3b62d78b75d6e871bc4bf0acf3960d7ecf41a2b597be6aeb1c5b54e6769b",
    "report.py": "4776eacef297fa0ea9be97d894e2274844f03e750b6385882a86bb19cf5df81a",
    "search.py": "71aab0ced5823038e40fd4085ccbd5dde3f1af648b2ef366b7c11e02e5c1d0e5",
    "tableio.py": "d752b22685d50bfeafd01b47d6230d696e2f99205d5711d72a98c650afd2eee6",
    "xmlio.py": "640eb6c9714f8b3396f175d5e1a3b36ada9d9e852d5943036ef1722dde3cebac",
}


def test_vendored_package_matches_pins():
    assert VENDORED.is_dir(), "vendored sieve_crowd/ is missing"
    actual = {}
    for path in sorted(VENDORED.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            key = str(path.relative_to(VENDORED))
            actual[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    missing = sorted(set(PINNED_SHA256) - set(actual))
    extra = sorted(set(actual) - set(PINNED_SHA256))
    assert not missing, "missing vendored files: " + ", ".join(missing)
    assert not extra, "unexpected vendored files: " + ", ".join(extra)
    diff = [
        name
        for name, sha in sorted(PINNED_SHA256.items())
        if actual[name] != sha
    ]
    assert not diff, (
        "vendored sieve_crowd/ differs from the pinned upstream copy; "
        + "; ".join(
            name + " pinned: " + PINNED_SHA256[name] + " actual: " + actual[name]
            for name in diff
        )
        + "; if the upstream update is intentional, re-vendor the package and "
        "refresh the pins, otherwise restore the pinned copy."
    )
