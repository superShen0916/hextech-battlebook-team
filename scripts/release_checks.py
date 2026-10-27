"""The frontend gate list shared by the builder and maintenance workflow."""
FRONTEND_CHECKS = (
    'verify-navigation.mjs', 'verify-version-intel.mjs', 'verify-recaps.mjs',
    'verify-structure.mjs', 'verify-match-details.mjs', 'verify-achievements.mjs',
    'verify-social.mjs',
)


def frontend_commands(node, frontend):
    yield [node, 'node_modules/typescript/bin/tsc', '--noEmit'], frontend
    for name in FRONTEND_CHECKS:
        yield [node, name], frontend
