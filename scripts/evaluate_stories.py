"""Real model samples for human review; technical success is not an editorial verdict."""
import json
import sys
import tempfile
from pathlib import Path
from app import story_engine
from app.story_engine import generate_story, stop_server

THEMES = {
 'familia': 'Mi hermano me pidió pagar el catering de su boda. Ya pagué la seña y el contrato está a su nombre. Descubrí que no estoy invitado porque a su novia le avergüenza que yo pinte casas. No quiero pagar el saldo.',
 'trabajo': 'Mi jefa presentó mi propuesta como si fuera de ella. Durante la reunión, el cliente me preguntó por un cálculo que solo yo había preparado. La propuesta tiene mi historial de versiones. Quiero que reconozcan mi trabajo sin perder el empleo.',
 'convivencia': 'Mi compañero de apartamento cobraba a escondidas por prestar mi habitación cuando yo viajaba. Descubrí una reseña que mostraba mi escritorio. El alquiler está a nombre de ambos; quiero recuperar mi privacidad sin inventar que puedo echarlo de inmediato.',
}
original_complete=story_engine.complete
def logged_complete(messages,json_mode=False):
 result=original_complete(messages,json_mode)
 print('MODEL_STAGE '+json.dumps(result,ensure_ascii=False),flush=True)
 return result
story_engine.complete=logged_complete
case=sys.argv[1]
try:
 with tempfile.TemporaryDirectory(prefix='story-eval-') as folder:
  result=generate_story(THEMES[case],60,Path(folder),lambda m:print(m,flush=True))
  print('EVALUATION_RESULT '+json.dumps({'case':case,'theme':THEMES[case],**result},ensure_ascii=False),flush=True)
finally:stop_server()
