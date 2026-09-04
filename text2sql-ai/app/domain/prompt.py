"""Pure prompt-assembly logic (Text2SQL_Sorabel.md §4) — turns a filtered schema +
static prompt ingredients into the system prompt sent to the generator LLM. No I/O;
every ingredient is passed in already loaded by the caller."""

from __future__ import annotations

from app.domain.models import SchemaTable

CRITICAL_INSTRUCTION = (
    "CRITICAL: utilise uniquement les noms de tables et de colonnes exacts listés "
    "ci-dessus, tels quels. N'invente jamais un nom de table ou de colonne."
)

READONLY_INSTRUCTION = (
    "Tu es un agent Text-to-SQL en lecture seule strict. Tu ne génères que des "
    "requêtes SELECT. Si la question demande une modification de données (ajout, "
    "suppression, mise à jour), refuse et explique que tu ne fais que de la lecture."
)

AMBIGUITY_INSTRUCTION = (
    "Si la question admet plusieurs interprétations métier (critère de tri, de "
    "mesure ou de période non précisé), ne devine pas : pose is_ambiguous à true, "
    "laisse sql à null et formule dans clarification_needed la question de "
    "clarification à poser à l'utilisateur."
)

OUT_OF_SCHEMA_INSTRUCTION = (
    "Si le schéma ci-dessus ne contient pas la donnée demandée, ne l'invente pas et "
    "ne la remplace pas par une colonne approchante : pose is_out_of_schema à true, "
    "laisse sql à null et indique dans clarification_needed quelle donnée manque."
)

INTENT_REFORMULATION_INSTRUCTION = (
    "Dès que tu produis une requête, renseigne intent_reformulation : une "
    "reformulation d'une seule ligne, en français, de ce que cette requête calcule "
    "réellement — pas une paraphrase de la question."
)

RESPONSE_FORMAT_INSTRUCTION = (
    f"{AMBIGUITY_INSTRUCTION}\n{OUT_OF_SCHEMA_INSTRUCTION}\n"
    f"{INTENT_REFORMULATION_INSTRUCTION}\n"
    "is_ambiguous et is_out_of_schema ne peuvent pas être vrais en même temps ; "
    "quand les deux sont faux, sql doit contenir une requête SELECT complète."
)


def _format_table(table: SchemaTable) -> str:
    lines = [f"Table {table.name} -- {table.comment}"]
    for column in table.columns:
        flags = []
        if column.is_primary_key:
            flags.append("PK")
        if column.is_foreign_key:
            flags.append("FK")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        enum_str = ""
        if column.enum_values:
            values = ", ".join(f"'{v}'" for v in column.enum_values)
            enum_str = f" -- valeurs possibles : {values}"
        lines.append(
            f"  {table.name}.{column.name} ({column.type}){flag_str} -- {column.comment}{enum_str}"
        )
    return "\n".join(lines)


def build_system_prompt(
    tables: list[SchemaTable],
    business_rules: dict[str, str],
    few_shot_examples: list[dict[str, str]],
) -> str:
    schema_block = "\n\n".join(_format_table(t) for t in tables)

    rules_lines = [f"- {term} : {definition}" for term, definition in business_rules.items()]
    rules_block = "\n".join(rules_lines) if rules_lines else "(aucune règle métier spécifique)"

    example_lines = [
        f"Question : {example['question']}\nSQL : {example['sql']}" for example in few_shot_examples
    ]
    examples_block = "\n\n".join(example_lines) if example_lines else "(aucun exemple)"

    return (
        f"{READONLY_INSTRUCTION}\n\n"
        f"## Schéma disponible\n{schema_block}\n\n"
        f"## Règles métier\n{rules_block}\n\n"
        f"## Exemples\n{examples_block}\n\n"
        f"## Format de réponse\n{RESPONSE_FORMAT_INSTRUCTION}\n\n"
        f"{CRITICAL_INSTRUCTION}"
    )
