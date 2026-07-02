import pathlib
import sys

# 把 shared/py 加入 sys.path，好 import glossary / pdf_triage / claude_client / supabase_client / settings
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
