# 🚀 Deployment Instructies – McDonald's Management Dashboard

## Structuur van de applicatie

```
mcdonalds_scheduler/
├── app.py              # Hoofdapplicatie (Streamlit entry point)
├── data_model.py       # Dataklassen & modellen
├── constraints.py      # CAO Horeca 2025-2026 & ATW regels
├── solver.py           # OR-Tools CP-SAT solver + greedy fallback
├── ui.py               # Alle 9 UI-tabs
├── utils.py            # Export (Excel, PDF, iCal), KPI, import
├── requirements.txt    # Python-dependencies
├── deployment.md       # Dit bestand
└── .streamlit/
    └── secrets.toml    # Wachtwoordconfiguratie (NIET committen!)
```

---

## Optie 1 – Streamlit Community Cloud (gratis, aanbevolen)

### Stap 1: GitHub repository aanmaken
1. Maak een **privé** repository aan op GitHub (bijv. `mcdonalds-rooster`).
2. Upload alle bestanden uit deze map naar de repo.
3. Voeg `.streamlit/secrets.toml` toe aan `.gitignore` zodat het wachtwoord
   NIET in GitHub terechtkomt.

### Stap 2: Secrets configureren
Maak **lokaal** het bestand `.streamlit/secrets.toml` aan:
```toml
dashboard_password = "jouwsterkwachtwoord"
```
> ⚠️ Dit bestand NOOIT committen of delen!

### Stap 3: Deploy naar Streamlit Cloud
1. Ga naar [share.streamlit.io](https://share.streamlit.io) en log in met GitHub.
2. Klik **"New app"**.
3. Selecteer jouw repository en stel `app.py` in als main file.
4. Klik **"Advanced settings"** → **"Secrets"** en plak:
   ```
   dashboard_password = "jouwsterkwachtwoord"
   ```
5. Klik **"Deploy"** – de app is live binnen 2–3 minuten!

### URL
Je ontvangt een URL zoals:
`https://jouw-naam-mcdonalds-rooster.streamlit.app`

Deze URL is direct bruikbaar op telefoon en desktop.

---

## Optie 2 – Docker (zelf-gehoste server / VPS)

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
```

### docker-compose.yml
```yaml
version: "3.9"
services:
  dashboard:
    build: .
    ports:
      - "8501:8501"
    environment:
      - DASHBOARD_PASSWORD=jouwwachtwoord
    restart: unless-stopped
    volumes:
      - ./data:/app/data   # optioneel: persistente opslag
```

### Starten
```bash
docker compose up -d
```
App bereikbaar op: `http://jouw-server-ip:8501`

---

## Optie 3 – Lokaal draaien

```bash
# 1. Clone / download de bestanden
cd mcdonalds_scheduler

# 2. Installeer dependencies
pip install -r requirements.txt

# 3. Wachtwoord instellen (optioneel – standaard: mcdonalds2025)
mkdir -p .streamlit
echo 'dashboard_password = "jouwwachtwoord"' > .streamlit/secrets.toml

# 4. Start de app
streamlit run app.py
```

Browser opent automatisch op `http://localhost:8501`.

---

## Mobiel gebruik

De app is mobiel-first ontworpen. Voeg de URL toe aan je telefoon als
**thuisscherm-snelkoppeling** (PWA-achtig):
- **iPhone/iPad**: Safari → Delen → "Zet op beginscherm"
- **Android**: Chrome → Menu (⋮) → "Toevoegen aan startscherm"

---

## Beveiliging

| Aspect | Aanbeveling |
|--------|------------|
| Wachtwoord | Minimaal 12 tekens, mix van letters/cijfers |
| HTTPS | Streamlit Cloud: automatisch. Docker: gebruik Nginx reverse proxy + Let's Encrypt |
| Secrets | Nooit in git; gebruik environment variables of Streamlit secrets |
| Toegang | Deel de URL alleen met managers |

---

## OR-Tools installatie (solver)

OR-Tools wordt automatisch geïnstalleerd via `requirements.txt`.
Als de installatie mislukt (bijv. grote binaries), verwijder dan de regel
`ortools>=...` uit `requirements.txt` – de app gebruikt automatisch
de ingebouwde greedy-solver als fallback.

---

## Troubleshooting

| Probleem | Oplossing |
|----------|-----------|
| `ModuleNotFoundError: ortools` | `pip install ortools` of schakel greedy-modus in |
| `ModuleNotFoundError: reportlab` | `pip install reportlab` |
| `ModuleNotFoundError: icalendar` | `pip install icalendar` |
| App laadt niet op mobiel | Controleer of layout="wide" ingesteld is in `app.py` |
| Wachtwoord werkt niet | Controleer `secrets.toml` of `DASHBOARD_PASSWORD` env-var |
| Excel download leeg | `pip install openpyxl` |

---

## Versie-informatie

- **Streamlit**: ≥ 1.35
- **Python**: ≥ 3.10
- **OR-Tools**: ≥ 9.10
- **CAO**: Horeca 2025-2026 (KHN / De Horecabond)
- **ATW**: Arbeidstijdenwet (actuele versie 2025)
