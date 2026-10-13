import json
import pytest
from app.story_edits import apply_edits


def draft():
    return {'title': 'El auto', 'plan': 'El dueño conserva el auto.',
            'part1': 'Restauré mi auto durante meses y se lo presté a mi hermano para una entrevista.',
            'part2': 'El comprador devolvió la seña. Mi hermano borró el anuncio y yo conservé las llaves de mi auto.'}


def test_payment_correction_preserves_everything_else():
    source = draft()
    changed = apply_edits(source, json.dumps({'edits': [
        {'part': 'part2', 'before': 'El comprador devolvió la seña.',
         'after': 'Mi hermano devolvió la seña al comprador.'}]}))
    assert changed['part1'] == source['part1']
    assert changed['part2'] == 'Mi hermano devolvió la seña al comprador. Mi hermano borró el anuncio y yo conservé las llaves de mi auto.'
    assert source == draft()


@pytest.mark.parametrize('edits', [
    [{'part':'part2','before':'Un texto inventado','after':'Otro texto'}],
    [{'part':'part2','before':'Mi hermano','after':'Él'},
     {'part':'part1','before':'Texto que no existe','after':'Cambio'}],
    [{'part':'part2','before':'El comprador devolvió la seña.','after':'Cambio.'},
     {'part':'part2','before':'devolvió la seña','after':'pagó'}],
    [{'part':'part2','before':'El comprador devolvió la seña.','after':'El comprador devolvió la seña.'}],
    [{'part':'part2','before':draft()['part2'],'after':'Todo cambió.'}],
    [],
])
def test_invalid_corrections_are_atomic(edits):
    original = draft()
    with pytest.raises(ValueError):
        apply_edits(original, json.dumps({'edits': edits}))
    assert original == draft()


def test_duplicate_anchor_must_include_context():
    source = draft()
    source['part2'] = 'Me fui. ' + source['part2'] + ' Me fui.'
    with pytest.raises(ValueError):
        apply_edits(source, json.dumps({'edits': [
            {'part':'part2','before':'Me fui.','after':'Volví.'}]}))
