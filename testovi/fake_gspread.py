"""Lažni gspread Spreadsheet/Worksheet u memoriji — dovoljno za testiranje pipeline_upisi.py
bez pristupa pravom Google Sheetu. Vrijednosti se čuvaju kako su upisane (kao RAW)."""
import gspread
from gspread.utils import a1_to_rowcol


class FakeCell:
    def __init__(self, value):
        self.value = value


class FakeWorksheet:
    def __init__(self, title, rows=None):
        self.title = title
        self.data = [list(r) for r in (rows or [])]
        self.col_count = max([len(r) for r in self.data] + [26])
        self.pozivi = 0  # broj API poziva (za provjeru kvote)

    def _siri(self, r, c):
        while len(self.data) < r:
            self.data.append([])
        for red in self.data:
            while len(red) < c:
                red.append("")

    def row_values(self, r):
        self.pozivi += 1
        red = self.data[r - 1] if r - 1 < len(self.data) else []
        while red and red[-1] == "":
            red = red[:-1]
        return list(red)

    def col_values(self, c):
        self.pozivi += 1
        vals = [(r[c - 1] if c - 1 < len(r) else "") for r in self.data]
        while vals and vals[-1] == "":
            vals.pop()
        return vals

    def get_all_values(self, **kw):
        return [[("" if v is None else str(v)) for v in r] for r in self.data]

    def get_all_records(self, value_render_option=None, **kw):
        self.pozivi += 1
        if not self.data:
            return []
        h = self.row_values(1)
        out = []
        for r in self.data[1:]:
            out.append({k: (r[i] if i < len(r) else "") for i, k in enumerate(h)})
        return out

    def append_rows(self, values, value_input_option="RAW", **kw):
        for v in values:
            self.append_row(v, value_input_option)

    def append_row(self, values, value_input_option="RAW", **kw):
        self.pozivi += 1
        self.data.append(list(values))

    def cell(self, r, c):
        self.pozivi += 1
        try:
            return FakeCell(self.data[r - 1][c - 1])
        except IndexError:
            return FakeCell("")

    def update_cell(self, r, c, v):
        self.pozivi += 1
        self._siri(r, c)
        self.data[r - 1][c - 1] = v

    def _upisi_raspon(self, a1, values):
        prvi = a1.split(":")[0]
        r0, c0 = a1_to_rowcol(prvi)
        for i, red in enumerate(values):
            for j, v in enumerate(red):
                self._siri(r0 + i, c0 + j)
                self.data[r0 - 1 + i][c0 - 1 + j] = v

    def batch_update(self, data, raw=True, **kw):
        self.pozivi += 1
        for d in data:
            self._upisi_raspon(d["range"], d["values"])

    def update(self, values=None, range_name=None, **kw):
        self.pozivi += 1
        self._upisi_raspon(range_name, values)

    def add_cols(self, n):
        self.col_count += n

    def delete_rows(self, r, end=None):
        """Kao gspread: briše redak r, ili raspon r..end (1-based, uključivo).

        20.11.2026.: raspon je dodan jer `tablice.obrisi_gdje()` briše susjedne retke u bloku
        (jedan poziv umjesto jednog po retku — kvota 429).
        """
        self.pozivi += 1
        kraj = r if end is None else end
        del self.data[r - 1:kraj]


class FakeSpreadsheet:
    def __init__(self):
        self.tabs = {}

    def dodaj(self, title, headers, retci=None):
        ws = FakeWorksheet(title, [headers] + [[r.get(h, "") for h in headers] for r in (retci or [])])
        self.tabs[title] = ws
        return ws

    def worksheet(self, title):
        if title not in self.tabs:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self.tabs[title]

    def worksheets(self):
        return list(self.tabs.values())

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title)
        self.tabs[title] = ws
        return ws

    def kao_objekti(self, title):
        d = self.tabs[title].data
        return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(d[0])} for r in d[1:]]
