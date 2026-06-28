# Specyfikacja: automat do dopasowywania CV pod ogłoszenia (UE)

**Status:** zamknięta specyfikacja — punkt wyjścia do budowy
**Adresat budowy:** projekt składany z pomocą Claude Code, hostowany na własnym VPS
**Wersja:** 1.0

---

## 1. Cel i zakres

System wspomaga aplikowanie o pracę na rynku Unii Europejskiej. Z bazowego CV użytkownika i pojedynczego ogłoszenia produkuje **dopasowaną wersję CV w PDF**, którą użytkownik ocenia i decyduje, czy wysłać.

System **nie wysyła aplikacji samodzielnie**. Człowiek jest bramką decyzyjną na końcu. To założenie projektowe, nie ograniczenie tymczasowe.

**Poza zakresem (świadomie):** automatyczne składanie aplikacji na portalach, prowadzenie korespondencji z pracodawcą, śledzenie statusu rekrutacji.

---

## 2. Użytkownik i tryb pracy

- Jeden użytkownik (właściciel systemu), nie produkt wieloosobowy.
- Buduje i utrzymuje system z pomocą agenta (Claude Code), nie jest programistą.
- Tryb pracy systemu: **półautomat**. Pobieranie i generowanie może dziać się w tle (cron), ale akceptacja zawsze jest ręczna.

Konsekwencja dla projektu: prostota utrzymania > maksymalna automatyzacja. Każdy element ma działać tak, by jego awaria była widoczna i nie blokowała reszty.

---

## 3. Zasada architektoniczna nadrzędna

**Warstwa źródeł jest odcięta od silnika.**

Silnik dostaje ogłoszenie jako tekst w jednym, wspólnym formacie i nie wie ani nie obchodzi go, skąd ono przyszło — z ręcznego wklejenia, z API agregatora, czy ze scrapera. Dzięki temu:

- system działa od pierwszego dnia (kanał ręczny wystarcza),
- nowe źródła dokłada się pojedynczo, bez ruszania silnika,
- awaria jednego źródła nie wpływa na resztę.

To jest fundament całej budowy. Każda decyzja niżej ma go respektować.

---

## 4. Przepływ end-to-end

1. **Setup (raz):** użytkownik wgrywa bazowe CV i wybiera szablon graficzny PDF; ustawia parametry wyszukiwania (role, słowa kluczowe, kraje).
2. **Wejście ogłoszenia** jednym z trzech kanałów (rozdział 5) → sprowadzenie do wspólnego formatu.
3. **Ocena:** silnik zestawia ogłoszenie z bazowym CV, wystawia wynik dopasowania i streszcza, na czym ogłoszeniu zależy.
4. **Generacja:** dla ogłoszeń powyżej progu silnik tworzy dopasowaną treść CV (reorganizacja prawdziwej treści, bez dopisywania kompetencji).
5. **Layout:** treść wlewana w szablon → gotowy PDF.
6. **Poczekalnia:** lista gotowych CV obok ogłoszenia źródłowego i krótkiego uzasadnienia. Użytkownik: akceptuj / odrzuć / popraw / eksportuj.

---

## 5. Warstwa wejścia (kanały wymienne)

Każdy kanał ma jedno zadanie: dostarczyć ogłoszenie i sprowadzić je do **wspólnego formatu**:

```
{
  "tytul":   "...",
  "firma":   "...",
  "opis":    "...",        // pełna treść ogłoszenia
  "link":    "...",        // URL źródłowy, jeśli jest
  "kraj":    "...",
  "zrodlo":  "manual | adzuna | scraper:<nazwa>"
}
```

### 5.1. Kanał ręczny (priorytet 1 — MVP)
Użytkownik wkleja tekst ogłoszenia w pole w interfejsie. Działa zawsze, zero kruchości, daje **pełny opis** stanowiska (najlepszy materiał do dopasowania). To jest rdzeń, który musi działać przed wszystkim innym.

### 5.2. Kanał API agregatora — Adzuna (priorytet 2)
Oficjalne API Adzuny: darmowe konto deweloperskie (App ID + App Key), odpowiedź w formacie JSON, jedno stabilne wywołanie zamiast scrapera. Pobierane przez cron wg parametrów wyszukiwania.

**Ograniczenia, które trzeba uwzględnić w projekcie:**
- API zwraca **tylko fragment opisu**, nie pełną treść. Dla rzetelnego dopasowania trzeba dociągnąć pełny opis spod `link` — a tam częściowo wraca kruchość pobierania. System ma działać także na samym fragmencie (gorsze dopasowanie) i nie wywracać się, gdy pełnej treści nie da się pobrać.
- **Pokrycie krajów UE jest częściowe.** Oficjalne API obejmuje m.in. Polskę, Niemcy, Francję, Austrię — ale **nie wszystkie** kraje UE. Dla krajów spoza listy ten kanał odpada i zostają kanał ręczny oraz ewentualne scrapery.
- Darmowy poziom ma dzienne limity wywołań — cron ma je respektować.

### 5.3. Kanały scraperów (priorytet 3 — oportunistyczne)
Dokładane pojedynczo, tylko dla portali, które na to pozwalają i są łatwe do pobrania (bez agresywnego antybota / Cloudflare). Każdy scraper:
- jest opcjonalny i izolowany — jego awaria nie blokuje pozostałych kanałów,
- sprowadza wynik do wspólnego formatu jak każde inne źródło.

Portale z poważnymi blokadami **nie są celem** — tam wystarcza kanał ręczny.

---

## 6. Silnik — ocena ogłoszenia

Wejście: ogłoszenie (wspólny format) + bazowe CV.
Wyjście:
- **wynik dopasowania** (np. 0–100),
- **streszczenie wymagań** — na czym ogłoszeniu realnie zależy (twarde wymagania, mile widziane, ton),
- **luki** — czego w bazowym CV brakuje względem ogłoszenia.

Próg dopasowania jest parametrem konfiguracji (domyślnie ustawiony, użytkownik może zmienić). Ogłoszenia poniżej progu trafiają do poczekalni oznaczone, ale bez wygenerowanego CV — żeby nie palić wywołań modelu na słabe dopasowania.

---

## 7. Silnik — generacja CV

Wejście: ogłoszenie + bazowe CV + streszczenie wymagań z kroku oceny.
Wyjście: dopasowana treść CV w **ustrukturyzowanym formacie** (sekcje: dane, podsumowanie, doświadczenie, umiejętności itd.) — gotowa do wlania w szablon.

**Guardrail merytoryczny (twardy, nie kosmetyczny):**
Generacja **reorganizuje i przesuwa akcenty prawdziwej treści** — dobiera, co wyeksponować, jak sformułować podsumowanie, które doświadczenia podciągnąć wyżej. **Nie wolno jej dopisywać kompetencji, narzędzi ani doświadczeń, których nie ma w bazowym CV.** Powód jest praktyczny, nie etyczny ozdobnik: CV z dorobionymi kompetencjami sypie się na rozmowie. Bramka ręczna w poczekalni jest drugą linią obrony przed tym.

Do każdego wygenerowanego CV silnik dołącza **krótkie uzasadnienie** (2–4 zdania): dlaczego taki wynik, co wyeksponowano, jakie luki zostały. To skraca przegląd w poczekalni.

---

## 8. Layout / PDF

Domyślne podejście: **szablon HTML/CSS renderowany do PDF**. Powód: automatyzacja prostsza o rząd wielkości niż programowe sterowanie Figmą, a efekt wizualnie dowolnie dopracowany. Wybór konkretnego narzędzia renderującego (np. silnik oparty na headless Chromium albo dedykowana biblioteka HTML→PDF) zostawiam fazie budowy — Claude Code dobierze stabilną opcję pod VPS.

Wymagania na warstwę layoutu:
- jeden lub kilka szablonów do wyboru,
- wlanie ustrukturyzowanej treści z kroku generacji w pola szablonu,
- wynik: plik PDF gotowy do wysyłki (format docelowy aplikacji).

Figma pozostaje możliwa, jeśli użytkownik zechce nietypowej grafiki — ale jako wariant droższy w robocie, nie domyślny.

---

## 9. Poczekalnia (interfejs)

Prosty interfejs webowy, jeden użytkownik. Lista pozycji, każda zawiera:
- ogłoszenie źródłowe (tytuł, firma, link, źródło),
- wynik dopasowania + uzasadnienie,
- podgląd / pobranie wygenerowanego CV (PDF),
- akcje: **akceptuj / odrzuć / popraw / eksportuj**.

„Popraw" pozwala ręcznie edytować treść przed eksportem (poprawka nie wymaga ponownego wywołania modelu). Stan każdej pozycji (nowa / zaakceptowana / odrzucona / wyeksportowana) jest zapisywany.

Pole do wklejenia ogłoszenia ręcznego (kanał 5.1) jest częścią tego samego interfejsu.

---

## 10. Dane i przechowywanie

- **SQLite** — lekka baza w pliku, bez serwera bazodanowego. W zupełności wystarcza dla jednego użytkownika na VPS.
- Tabele (minimum): `ogloszenia`, `cv_wygenerowane`, `konfiguracja`.
- Bazowe CV i szablony przechowywane jako pliki + odwołania w bazie.
- Gotowe PDF-y zapisywane na dysku, dostępne z poczekalni.

---

## 11. Proponowany stos technologiczny

Dobrany pod profil „nie-programista + Claude Code + VPS" — priorytet: czytelność i łatwość utrzymania.

- **Język:** Python (naturalny dla integracji z API Adzuny i Anthropic, bogaty ekosystem do PDF; Claude Code dobrze go obsługuje).
- **Usługa web:** lekki framework (interfejs poczekalni + wklejanie). Jeden mały serwis.
- **Baza:** SQLite.
- **Model (ocena + generacja):** API Anthropic (Claude).
- **Harmonogram:** cron na VPS do pobierania z Adzuny.
- **PDF:** szablon HTML/CSS → render do PDF (narzędzie dobrane w budowie).

Stos jest propozycją domyślną; nie jest dogmatem, ale każda zmiana ma respektować zasadę z rozdziału 3.

---

## 12. Ograniczenia i koszty (uczciwie)

- **Koszt modelu:** każda ocena i generacja to płatne wywołanie API. Pojedynczo drobne, ale rośnie z liczbą ogłoszeń. Stąd próg dopasowania (rozdz. 6) — nie generujemy CV dla słabych trafień.
- **Jakość zależy od pełni opisu:** kanał ręczny daje najlepszy materiał; API Adzuny często tylko fragment (rozdz. 5.2).
- **Pokrycie UE niepełne przez API** — część krajów obsłuży tylko kanał ręczny / scraper.
- **Scrapery bywają kruche** — dlatego są oportunistyczne i izolowane, nie fundament.
- **System jest półautomatyczny z założenia** — nie zastępuje decyzji o wysłaniu.

---

## 13. Kolejność budowy (od kręgosłupa do rozszerzeń)

**Etap 1 — MVP (kręgosłup, działa sam w sobie):**
Kanał ręczny → ocena → generacja (z guardrailem) → PDF z szablonu → poczekalnia.
Po tym etapie system jest już użyteczny: wklejasz ogłoszenie, dostajesz dopasowane CV do przeglądu.

**Etap 2 — źródło hurtowe:**
Integracja API Adzuny + cron + dociąganie pełnego opisu spod linku.

**Etap 3 — rozszerzenia oportunistyczne:**
Pojedyncze scrapery dla przyjaznych portali. Każdy dokładany osobno.

Etapy 2 i 3 nie ruszają silnika z etapu 1 — to jest test poprawności architektury z rozdziału 3.

---

## 14. Założenia do potwierdzenia przed budową

Niewiele, ale realnie wpływa na kształt:

1. **Branża i konkretne kraje docelowe** — przesądza, czy API Adzuny w ogóle ma sens dla Ciebie (pokrycie i gęstość ogłoszeń są nierówne; role IT pokryte gęsto, niszowe/lokalne słabiej). Jeśli Twoje kraje są poza listą Adzuny, etap 2 odpada i zostaje kanał ręczny + scrapery.
2. **Liczba szablonów PDF na start** — założono jeden; jeśli chcesz kilka do wyboru, warstwa layoutu projektuje się od razu pod wybór.
3. **Język CV** — jeden bazowy język czy generowanie wersji w języku ogłoszenia (to drugie zwiększa złożoność generacji i warto wiedzieć z góry).

---

*Następny krok w trybie projektowym: osobna rozmowa „Zbuduj według tej specyfikacji — etap 1 (MVP), jeden spójny projekt".*
