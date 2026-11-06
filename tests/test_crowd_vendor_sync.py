"""Vendored sieve_crowd/ must byte-match the pinned upstream release.

The pins below are refreshed only when the vendored package is
intentionally re-vendored from the upstream Sieve Crowd repository
(v0.9.0 = main def0053, tree a06c92a6105d9a06932c534aca831b5f306f9d10).
Every vendored file is re-checked against these pins on each test run,
so silent drift between the two fails the build and a human reviews
the diff (intentional update vs missed sync).
"""

import hashlib
import pathlib

VENDORED = pathlib.Path(__file__).resolve().parent.parent / "sieve_crowd"
PINNED_SHA256 = {
    "__init__.py": "8d0099cc26b14df1c5b14c2b037875811cdb970bc96e4fe81cf45e8cc41663ad",
    "__main__.py": "935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d",
    "audit.py": "ccbe07c7f0e1a647bea7b64aaa785264b517484961bfdc6e1a62253ac4f21684",
    "chartable.py": "4a01afa04a9678d86a0562ae48a2b578b2dd547247d941762088fcf32405b7a5",
    "chartable_v1.json": "c5ae4757bc9d07a2dcd1507d662460c3412c932d73318e54912569608242e605",
    "cli.py": "a4887a7100fe642a1f2b6119be0456297e6297992a5a00813c578a5f95b8fa29",
    "config.py": "3fc0b1f9e95b7f05c88b4bf00f37faa6f529fd9e1c3fa000c54c137bd16d3a3d",
    "csvio.py": "80a90e8e714093e385a1245e53ab1c83bc942b81c5fb0a1359f817beb2a985b5",
    "derived.py": "2123cc0d4b2ef5dc5e2ecccf718827512278339e7cf3e02379fa4518e82076f8",
    "engine.py": "d7384c5eb5c6012f731ab9af04e0483ca92316b6b73b980f4a88a3541616dc5d",
    "generalize.py": "a5c0c7fdb306e028ade1c51b69872f030a6d13e54d9b1cb6c57023037839cea0",
    "hidden_chars.py": "47bd0aa3a83b0b33a39ef8a3d353efd4251f713eefcbfcb834f25317a5a672f5",
    "hintpack.py": "8aa8282680f32ccf7c67a5ada9692c82ecd291374db233a7fcab3f19f607267e",
    "hintpack_builtin.py": "6af10633a228aa5fd0f58312af63e120ff5d1a72153db1eac22eadd2b281aed9",
    "hints.py": "a0d79c844380a2ac0d21900be0ad7d7d65a64f064266516a5674cf23ff8271d3",
    "jsonio.py": "60a5b1ea05137ad3f6ab710eb11879b19b528658e95452db7c15f98cc8891cd9",
    "measure.py": "21ed70795ae40971c3447674736e58f06c0569cab14b8c3c52d946231b853a15",
    "model.py": "620bb06b38a17a264e01853d7458b0a8fcc9e32ddbb9d4cd547ed8a79a9a6a0f",
    "prng.py": "8e8eefe63cb711c72e5bd2da43ea198245361692796a1529b402d72bc5728594",
    "pseudonym.py": "e58d3b62d78b75d6e871bc4bf0acf3960d7ecf41a2b597be6aeb1c5b54e6769b",
    "report.py": "9ff81387e24e5e8ca2ab4153a2e3a677a2c66be08e83e44ec98c932f377b7c6a",
    "scan.py": "482ee976cf25735ffeb4990c8feb5ef3ab859fca4312aec0ba30cb96b066d906",
    "search.py": "b782ecb5a9c771e325782a6d08bc4081cde21bb1dbc98f00dc94c2e6967efbb4",
    "tableio.py": "cdd8ae2722e1ffb2f18f9e5e084c80a3caffabaac0f37db0fc8970f1b88ff6b4",
    "tabular.py": "b838bf53429320f42c7d4a10be640e233dd41bd2c00648ff56f66530996c9179",
    "xlsx_reader.py": "a7c6e8c3a4aa6dad1d56fcaf9b457ab3aad7d995781e529a3886e215fdee4da9",
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
