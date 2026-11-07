# Astra Academic

Answers study questions only from your own books and lecture notes, and cites the lecture name, lecture number and slide number.
No account. Sessions are saved in your browser (IndexedDB).

## Run it
- Windows: double-click `start.bat`. Mac/Linux: run `./start.sh`. Then use http://localhost:8000.
- Or host the folder on any static host (GitHub Pages, Netlify). Opening `index.html` directly will not work
  because the browser blocks reading the library files.
- Open **Settings**, paste a Gemini API key (keys are unlabeled; the model is fixed) (free at https://aistudio.google.com/apikey).

Note: the PDFs in `library/` are served to anyone who can open the site. Do not publish copyrighted books on a public host.

## How it answers
1. **Read**: your text, photos or PDFs are turned into a list of questions. Non-academic messages are declined.
2. **Route**: the model reads `library/map.json` (a short summary of every small PDF) and picks the files most likely to hold the answer.
3. **Solve**: those files are read page by page in the browser; each page carries its real book page number.
   The answer is built only from them. Quotes are checked against the page text and pages are corrected if needed.
4. **Fall back**: if the answer is not there, it searches other files (up to two more rounds). If nothing has it,
   the card says "Closest match" and lists the closest pages. It never answers from memory.
5. **Follow-up**: the box under each answer uses that answer's own sources first, then other files if they are not enough.

## Add a book (owner only, outside the app)
    pip install pypdf
    python tools/build_library.py "Book.pdf" --title "Book title" --id book-id --summarize gemini --key YOUR_KEY

Books are added by whoever prepares the app, not by the person using it. Reload the page afterwards.
The app has no screen for browsing or adding sources: sources only appear under each answer, after a question is solved.

| Option | Use |
|---|---|
| `--ranges "1-6:Intro;7-20:Chapter 1"` | split exactly where you want (titles optional) |
| `--max-pages 8` | largest file when splitting by bookmarks or fixed blocks (default 8) |
| `--page-offset 14` | printed page = PDF page minus 14 (earlier pages are skipped) |
| `--summaries file.json` | your own summaries, see `tools/example_summaries.json` |
| `--dry-run` | preview the split |

Without `--summarize` or `--summaries`, the map uses a plain text excerpt, which routes less accurately.
Re-running with the same `--id` replaces that book.

## Limits
- Text is read from the PDF. Scanned pages without text are sent as images automatically; slide images are always sent too, so diagrams work.
- A PDF of questions can be about 14 MB per message.
- Free Gemini keys have rate limits; add several keys and leave Smart rotation on.

## Library contents
Lectures 1-15 (Anatomy) plus the extra material: Lecture 5 missing slide, Lecture 7 missing slides,
board drawings for Lectures 9 and 12. Lectures 2-15 have automatically extracted summaries
(slide titles plus the first words of each slide); Lecture 1 and the photos have hand-written ones.
