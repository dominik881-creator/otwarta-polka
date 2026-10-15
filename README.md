# Otwarta Półka

Katalog aplikacji open source w stylu sklepu Play: kategorie, ikony, zrzuty ekranu i opisy prostym polskim językiem.

- **Źródła:** Flathub (programy na komputer, Linux) i F-Droid (Android). Brane są tylko apki z otwartą licencją; porzucone (bez aktualizacji od roku) odpadają.
- **Opisy:** Groq (`openai/gpt-oss-20b`) pisze po polsku hasło, 2–3 zdania opisu, kategorię i „zamiast czego” (np. GIMP → Photoshop). Każda apka jest opisywana raz, wynik leży w `cache/opisy.json`.
- **Odświeżanie:** GitHub Actions codziennie rano. Za darmo.
- **Śledzenie:** przycisk „Obserwuj” na karcie apki. Gdy obserwowana apka dostanie aktualizację, zobaczysz to na stronie głównej. Kropka przy ikonie = nowość od ostatniej wizyty.

```
fetch.py                     zbiera dane i woła Groq
docs/index.html              strona (czyta docs/data.json)
docs/data.json               wynik, generowany automatycznie
cache/opisy.json             zapamiętane opisy
.github/workflows/odswiez.yml  codzienny automat
```

## Uruchomienie na GitHubie (raz, ~10 minut)

1. Załóż nowe repozytorium na GitHubie (może być prywatne, ale GitHub Pages za darmo działa tylko na publicznych).
2. Wrzuć do niego wszystkie pliki z tego folderu (z ukrytym folderem `.github`).
3. **Settings → Secrets and variables → Actions → New repository secret**: nazwa `GROQ_API_KEY`, wartość: twój klucz z console.groq.com.
4. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder `/docs`. Zapisz.
5. **Actions → Odśwież półkę → Run workflow**. Pierwsze uruchomienie trwa 10–20 minut (opisuje ~600 apek; F-Droid to duży plik).
6. Strona będzie pod adresem `https://TWOJ-LOGIN.github.io/NAZWA-REPO/`. Na telefonie w Chrome: menu → *Dodaj do ekranu głównego* i masz ikonę jak apka.

## Uruchomienie lokalnie (Windows)

```powershell
pip install requests
$env:GROQ_API_KEY="gsk_..."
python fetch.py
cd docs
python -m http.server 8000
```
Potem otwórz http://localhost:8000. (Samo dwukrotne kliknięcie `index.html` nie zadziała, przeglądarka blokuje wczytanie `data.json` z dysku.)

## Ustawienia

Na górze `fetch.py`:

| Zmienna | Domyślnie | Co robi |
|---|---|---|
| `FLATHUB_POPULAR` | 300 | ile najpopularniejszych apek z Flathub |
| `FLATHUB_TRENDING` | 80 | ile z listy „na topie” |
| `FDROID_LIMIT` | 300 | ile apek z F-Droid (z tokenem GitHub sortowane po gwiazdkach, bez niego po dacie aktualizacji) |
| `FDROID_MAX_AGE_DAYS` | 365 | pomija apki bez aktualizacji dłużej niż tyle dni |
| `MAX_NEW` (env) | 400 | ile nowych opisów na jedno uruchomienie; reszta dojdzie następnego dnia |
| `GROQ_MODEL` (env) | openai/gpt-oss-20b | model Groq |

Kategorie są w liście `CATEGORIES`. Jeśli je zmienisz, usuń `cache/opisy.json`, żeby apki zostały przypisane od nowa.

## Limity Groq

Opisy idą paczkami po 8 apek, więc pierwsze uruchomienie to ok. 75 zapytań, a kolejne dni tylko kilka (same nowe apki). Przy przekroczeniu limitu skrypt czeka i ponawia. Bez klucza strona też działa, tylko z oryginalnymi angielskimi opisami.
