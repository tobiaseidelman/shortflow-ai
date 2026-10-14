"""Apply bounded, anchored continuity corrections without regenerating whole episodes."""
import json

EDIT_SCHEMA = {
    'type': 'object', 'required': ['edits'], 'additionalProperties': False,
    'properties': {'edits': {'type': 'array', 'maxItems': 8, 'items': {
        'type': 'object', 'required': ['part', 'before', 'after'],
        'additionalProperties': False,
        'properties': {'part': {'type': 'string', 'enum': ['part1', 'part2']},
                       'before': {'type': 'string', 'minLength': 1},
                       'after': {'type': 'string'}}}}},
}


def apply_edits(draft, raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('edits'), list):
        raise ValueError('Falta la lista de correcciones.')
    edits = data['edits']
    if not 1 <= len(edits) <= 8:
        raise ValueError('La corrección debe contener entre uno y ocho cambios.')
    spans = {'part1': [], 'part2': []}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'part', 'before', 'after'}:
            raise ValueError('Corrección incompleta.')
        part, before, after = edit['part'], edit['before'], edit['after']
        if part not in spans or not isinstance(before, str) or not before or not isinstance(after, str):
            raise ValueError('Fragmento inválido.')
        if before == after or draft[part].count(before) != 1:
            raise ValueError('El fragmento debe aparecer exactamente una vez y cambiar.')
        start = draft[part].index(before)
        # Models may quote a whole paragraph to locate a one-word correction.
        # Count and apply only the actual changed span, preserving the quoted context.
        prefix = 0
        while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
            prefix += 1
        suffix = 0
        while (suffix < min(len(before), len(after)) - prefix and
               before[-suffix - 1] == after[-suffix - 1]):
            suffix += 1
        end = start + len(before) - suffix
        start += prefix
        after = after[prefix:len(after) - suffix if suffix else len(after)]
        if any((start < old_end and end > old_start) or
               (start == end and old_start <= start <= old_end) or
               (old_start == old_end and start <= old_start <= end)
               for old_start, old_end, _ in spans[part]):
            raise ValueError('Las correcciones se superponen.')
        spans[part].append((start, end, after))
    result = dict(draft)
    for part, replacements in spans.items():
        # Check against the original; one replacement cannot create another's anchor.
        if sum(end - start for start, end, _ in replacements) > len(draft[part]) / 2:
            raise ValueError('La corrección intentó reescribir la mayor parte del episodio.')
        text = draft[part]
        for start, end, after in sorted(replacements, reverse=True):
            text = text[:start] + after + text[end:]
        result[part] = text
    return result


def repair_draft(complete, theme, draft, issues):
    raw = complete([
        {'role': 'system', 'content':
         'Corregí únicamente los errores señalados en un relato español. '
         'Devolvé reemplazos puntuales: part identifica el episodio; before copia EXACTAMENTE '
         'el fragmento original, con puntuación y espacios; after contiene su corrección. '
         'Conservá todos los hechos no afectados. No reescribas el episodio entero, no ajustes '
         'su extensión ni agregues reconciliaciones. Si un fragmento se repite, incluí suficiente '
         'contexto para identificar una sola aparición. Los cambios no deben superponerse. '
         'El tema tiene prioridad sobre cualquier invención del borrador. Resolvé quién es dueño, '
         'quién actúa y quién devuelve dinero a quién cuando el error trate de eso.'},
        {'role': 'user', 'content': json.dumps(
            {'tema_original': theme, 'part1': draft['part1'], 'part2': draft['part2'],
             'errores': issues}, ensure_ascii=False)},
    ], json_mode=EDIT_SCHEMA)
    return apply_edits(draft, raw)
