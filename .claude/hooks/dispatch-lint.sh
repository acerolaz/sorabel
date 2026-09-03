#!/usr/bin/env bash
# Route le lint vers `make lint` du projet concerné, selon l'extension du fichier
# modifié — reste agnostique de la stack (ruff pour Python, dotnet format pour C#),
# cf. .claude/rules/makefile-conventions.md.
#
# TODO : implémenter la détection du projet racine (remontée jusqu'au Makefile le plus
# proche) et l'appel effectif à `make lint`.

set -euo pipefail

echo "dispatch-lint.sh: squelette non encore implémenté" >&2
exit 0
