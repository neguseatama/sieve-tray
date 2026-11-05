"""Vendored sieve_crowd/ must byte-match the pinned upstream release.

The pins below are refreshed only when the vendored package is
intentionally re-vendored from the published Sieve Crowd repository
(tag v0.8.2). Every vendored file is re-checked against these pins on
each test run, so silent drift between the two fails the build and a
human reviews the diff (intentional update vs missed sync).
"""

import hashlib
import pathlib

VENDORED = pathlib.Path(__file__).resolve().parent.parent / "sieve_crowd"
PINNED_SHA256 = {
    "__init__.py": "2176374c9418fd0dba83d456de89852b0d4e4a3f1ce8ebf2a109efe4a0643057",
    "__main__.py": "935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d",
    "audit.py": "ccbe07c7f0e1a647bea7b64aaa785264b517484961bfdc6e1a62253ac4f21684",
    "chartable.py": "4a01afa04a9678d86a0562ae48a2b578b2dd547247d941762088fcf32405b7a5",
    "chartable_v1.json": "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605",
    "cli.py": "39869af6acbec555a3a93e6df5fa524f48e0f1144f0826083452dc2897101356",
    "config.py": "3fc0b1f9e95b7f05c88b4bf00f37faa6f529fd9e1c3fa000c54c137bd16d3a3d",
    "csvio.py": "a44bc5be874c6dbbb26b4c5d852cc424ba826614233ebea1c3a5e2c8b0b538fa",
    "derived.py": "2123cc0d4b2ef5dc5e2ecccf718827512278339e7cf3e02379fa4518e82076f8",
    "engine.py": "d7384c5eb5c6012f731ab9af04e0483ca92316b6b73b980f4a88a3541616dc5d",
    "generalize.py": "a5c0c7fdb306e028ade1c51b69872f030a6d13e54d9b1cb6c57023037839cea0",
    "hidden_chars.py": "47bd0aa3a83b0b33a39ef8a3d353efd4251f713eefcbfcb834f25317a5a672f5",
    "hintpack.py": "8aa8282680f32ccf7c67a5ada9692c82ecd291374db233a7fcab3f19f607267e",
    "hintpack_builtin.py": "6af10633a228aa5fd0f58312af63e120ff5d1a72153db1eac22eadd2b281aed9",
    "hints.py": "a0d79c844380a2ac0d21900be0ad7d7d65a64f064266516a5674cf23ff8271d3",
    "jsonio.py": "60a5b1ea05137ad3f6ab710eb11879b19b528658e95452db7c15f98cc8891cd9",
    "measure.py": "21ed70795ae40971c3447674736e58f06c0569cab14b8c3c52d946231b853a15",
    "model.py": "5bd109dfd9183e59bd66abc4257b47776870d1e18472dee3a33e064173fde496",
    "prng.py": "8e8eefe63cb711c72e5bd2da43ea198245361692796a1529b402d72bc5728594",
    "pseudonym.py": "e58d3b62d78b75d6e871bc4bf0acf3960d7ecf41a2b597be6aeb1c5b54e6769b",
    "report.py": "9ff81387e24e5e8ca2ab4153a2e3a677a2c66be08e83e44ec98c932f377b7c6a",
    "scan.py": "482ee976cf25735ffeb4990c8feb5ef3ab859fca4312aec0ba30cb96b066d906",
    "search.py": "b782ecb5a9c771e325782a6d08bc4081cde21bb1dbc98f00dc94c2e6967efbb4",
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
