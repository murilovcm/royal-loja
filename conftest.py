import os
import sys

# Garante que módulos da raiz do projeto (shipping.py, app.py) sejam
# importáveis pelos testes em tests/, independente de como o pytest é
# invocado (`pytest` ou `python -m pytest`).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
