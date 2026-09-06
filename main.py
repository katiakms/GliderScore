from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.checkbox import CheckBox
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.popup import Popup
from datetime import datetime
import json
import math
import os


class TimeInput(TextInput):
    """Campo de tempo com máscara automática MM:SS.
    Os dígitos digitados entram pela direita (como um cronômetro):
    digitar 9, 5, 9 mostra 00:09 -> 00:59 -> 09:59.
    """

    def __init__(self, digits="", **kwargs):
        super().__init__(**kwargs)
        self._digits = ''.join(ch for ch in (digits or '') if ch.isdigit())[-4:]
        self._reformat()

    def _reformat(self):
        digits = self._digits.zfill(4) if self._digits else ''
        self.text = f"{digits[:2]}:{digits[2:]}" if digits else ''
        self.cursor = (len(self.text), 0)

    def insert_text(self, substring, from_undo=False):
        digits = ''.join(ch for ch in substring if ch.isdigit())
        if not digits:
            return
        for ch in digits:
            self._digits = (self._digits + ch)[-4:]
        self._reformat()

    def do_backspace(self, from_undo=False, mode='bkspc'):
        self._digits = self._digits[:-1]
        self._reformat()

# --------------------------
# Cores
# --------------------------
BG = "#0f1115"
CARD = "#1a1d24"
CARD2 = "#20242e"
BORDER = "#2c313c"
TEXT = "#eef1f7"
MUTED = "#9aa4b2"
PRIMARY = "#0d6efd"
DANGER = "#e5484d"
GOLD = "#ffd166"
GOOD = "#2ecc71"


def hexcolor(h, a=1):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)


# --------------------------
# Constantes de pontuação (FAI SC4 Vol F5, 5.5.11.12 - Class F5J Scoring)
# --------------------------
ARQUIVO_DADOS = "f5j_data.json"

MAX_FLIGHT_SECONDS = 900          # 5.5.11.13 e) 15 min - Working Time do fly-off (cobre também as rondas de 10 min)
OVERFLY_TOLERANCE_SECONDS = 60    # 5.5.11.12 g) zero se ultrapassar o Working Time em +1 min

HEIGHT_LIMIT_M = 200              # 5.5.11.12 e)
HEIGHT_PENALTY_PER_M_UNDER = 0.5  # pontos deduzidos por metro até 200 m
HEIGHT_PENALTY_PER_M_OVER = 3.0   # pontos deduzidos por metro acima de 200 m

# Tabela oficial de bônus de pouso, 5.5.11.12 h) - distância (m) -> pontos
LANDING_BONUS_TABLE = [
    (1, 50), (2, 45), (3, 40), (4, 35), (5, 30),
    (6, 25), (7, 20), (8, 15), (9, 10), (10, 5),
]  # acima de 10 m = 0 pontos


def parse_time_seconds(text):
    """Aceita 'MM:SS' ou apenas segundos. Retorna segundos (float)."""
    if not text:
        return 0.0
    text = str(text).strip()
    if not text:
        return 0.0
    if ':' in text:
        parts = text.split(':')
        try:
            minutes = float(parts[0]) if parts[0] != '' else 0.0
            seconds = float(parts[1]) if len(parts) > 1 and parts[1] != '' else 0.0
        except ValueError:
            return 0.0
        return minutes * 60 + seconds
    try:
        return float(text)
    except ValueError:
        return 0.0


def landing_points(dist, over_10=False):
    """Bônus de pouso pela tabela oficial (5.5.11.12 h).
    Até 1 m = 50 pontos, decrescendo 5 pontos por metro até 10 m; acima de 10 m = 0.
    `over_10` permite marcar "pouso além de 10 m" sem precisar da distância exata.
    """
    if over_10:
        return 0.0
    if dist in (None, ""):
        return 0.0
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return 0.0
    if d < 0:
        d = 0.0
    if d > 10:
        return 0.0
    for limite, pontos in LANDING_BONUS_TABLE:
        if d <= limite:
            return float(pontos)
    return 0.0


def height_deduction(height):
    """Dedução pela altura de lançamento / Start Height (5.5.11.12 d, e).
    Truncada para o metro inteiro; 0,5 pt/m até 200 m e 3 pts/m acima disso.
    """
    if height in (None, ""):
        return 0.0
    try:
        h = float(height)
    except (TypeError, ValueError):
        return 0.0
    if h <= 0:
        return 0.0
    h = math.floor(h)
    if h <= HEIGHT_LIMIT_M:
        return h * HEIGHT_PENALTY_PER_M_UNDER
    return (HEIGHT_LIMIT_M * HEIGHT_PENALTY_PER_M_UNDER
            + (h - HEIGHT_LIMIT_M) * HEIGHT_PENALTY_PER_M_OVER)


def raw_score(flight):
    """Total Points conforme 5.5.11.12: tempo de voo (limitado a MAX_FLIGHT_SECONDS)
    + bônus de pouso - dedução de altura, truncado em zero se negativo.
    Voo é zerado inteiro se: reinício do motor (AMRT reseta a Start Height, 5.5.1.3.iii),
    pouso fora de 75 m do centro (cancelamento, 5.5.11.7 d), ou passar do Working Time
    em mais de 1 minuto (5.5.11.12 g). Penalidades (5.5.11.4) ainda não são consideradas aqui.
    """
    if not flight:
        return 0.0
    time_txt = flight.get("time", "")
    landing_txt = flight.get("landing", "")
    height_txt = flight.get("height", "")
    if (time_txt in (None, "")) and (landing_txt in (None, "")) and (height_txt in (None, "")):
        return 0.0

    if flight.get("motor_restarted") or flight.get("landing_over_75"):
        return 0.0

    time_val = parse_time_seconds(time_txt)
    time_val = math.floor(time_val)  # 5.5.11.12 b) truncado ao segundo inteiro

    if time_val > MAX_FLIGHT_SECONDS + OVERFLY_TOLERANCE_SECONDS:
        return 0.0  # 5.5.11.12 g)

    time_points = min(time_val, MAX_FLIGHT_SECONDS)
    landing_val = landing_points(landing_txt, over_10=bool(flight.get("landing_over_10")))
    height_pen = height_deduction(height_txt)

    total = time_points + landing_val - height_pen
    return max(0.0, total)  # 5.5.11.12 f)


class CompeticaoStore:
    """Gerencia os dados da competição (pilotos, rounds, voos) em JSON."""

    def __init__(self, arquivo=ARQUIVO_DADOS):
        self.arquivo = arquivo
        self.dados = self.padrao()
        self.carregar()

    def padrao(self):
        return {
            "setup_done": False,
            "event_name": "",
            "num_pilotos": 6,
            "num_rounds": 5,
            "pilotos": [],       # [{"name": "..."}]
            "flights": {},       # {"1": {"0": {"time","landing","height","landing_over_75","motor_restarted"}}}
            "current_round": 1,
        }

    def carregar(self):
        if os.path.exists(self.arquivo):
            try:
                with open(self.arquivo, "r", encoding="utf-8") as f:
                    self.dados = json.load(f)
            except Exception as e:
                print(f"Erro ao carregar dados: {e}")
                self.dados = self.padrao()
        else:
            self.dados = self.padrao()

    def salvar(self):
        try:
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump(self.dados, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Erro ao salvar dados: {e}")
            return False

    def resetar(self):
        self.dados = self.padrao()
        self.salvar()

    # ---------- Pontuação ----------
    def normalized_round(self, round_num):
        """Retorna {pilot_idx: nota_normalizada} para um round.
        O maior valor bruto (Total Points) do round vira 1000; os demais são proporcionais.
        """
        flights = self.dados["flights"].get(str(round_num), {})
        raws = {}
        best = 0.0
        for i in range(self.dados["num_pilotos"]):
            r = raw_score(flights.get(str(i)))
            raws[i] = r
            if r > best:
                best = r
        norm = {}
        for i in range(self.dados["num_pilotos"]):
            norm[i] = (raws[i] / best * 1000.0) if best > 0 else 0.0
        return norm

    def totals(self):
        """Soma das notas normalizadas de cada round = 'Raw'/'Score' do piloto no geral."""
        totals = [0.0] * self.dados["num_pilotos"]
        for r in range(1, self.dados["num_rounds"] + 1):
            norm = self.normalized_round(r)
            for i in range(self.dados["num_pilotos"]):
                totals[i] += norm[i]
        return totals

    def resultado_geral(self):
        """Monta a tabela de resultados no estilo Rank/Name/Score/Pcnt/Raw/Rnd1... .
        Pode ser chamado a qualquer momento, mesmo com rounds não voados (contam como 0).
        """
        d = self.dados
        totals = self.totals()
        norms_por_round = {r: self.normalized_round(r) for r in range(1, d["num_rounds"] + 1)}
        ordem = sorted(range(d["num_pilotos"]), key=lambda i: totals[i], reverse=True)
        melhor = totals[ordem[0]] if ordem and totals[ordem[0]] > 0 else 0.0

        linhas = []
        for pos, i in enumerate(ordem):
            pcnt = (totals[i] / melhor * 100.0) if melhor > 0 else 0.0
            rounds_vals = [norms_por_round[r][i] for r in range(1, d["num_rounds"] + 1)]
            linhas.append({
                "rank": pos + 1,
                "name": d["pilotos"][i]["name"],
                "score": totals[i],
                "pcnt": pcnt,
                "raw": totals[i],
                "rounds": rounds_vals,
            })
        return linhas


def styled_bg(widget, color_hex):
    with widget.canvas.before:
        Color(*hexcolor(color_hex))
        rect = Rectangle(pos=widget.pos, size=widget.size)

    def update(instance, value):
        rect.pos = instance.pos
        rect.size = instance.size

    widget.bind(pos=update, size=update)


def make_label(text, size='14sp', bold=False, color=TEXT, halign='left'):
    lbl = Label(
        text=text,
        font_size=size,
        bold=bold,
        color=hexcolor(color),
        halign=halign,
        valign='middle',
        size_hint_y=None,
        height=dp(26),
    )
    lbl.bind(size=lambda *a: setattr(lbl, 'text_size', lbl.size))
    return lbl


def make_button(text, bg=PRIMARY, color=TEXT, height=48):
    btn = Button(
        text=text,
        background_normal='',
        background_color=hexcolor(bg),
        color=hexcolor(color),
        size_hint_y=None,
        height=dp(height),
        font_size='15sp',
        bold=True,
    )
    return btn


def make_input(hint="", text="", input_filter=None, width=None):
    ti = TextInput(
        text=text,
        hint_text=hint,
        multiline=False,
        size_hint_y=None,
        height=dp(42),
        font_size='14sp',
        background_color=hexcolor(CARD2),
        foreground_color=hexcolor(TEXT),
        hint_text_color=hexcolor(MUTED),
        padding=[dp(10), dp(10), dp(10), dp(10)],
        input_filter=input_filter,
    )
    if width:
        ti.size_hint_x = None
        ti.width = dp(width)
    return ti


def make_time_input(digits_text="", width=70):
    ti = TimeInput(
        digits=digits_text,
        multiline=False,
        size_hint_y=None,
        height=dp(42),
        font_size='14sp',
        background_color=hexcolor(CARD2),
        foreground_color=hexcolor(TEXT),
        hint_text_color=hexcolor(MUTED),
        padding=[dp(10), dp(10), dp(10), dp(10)],
    )
    ti.size_hint_x = None
    ti.width = dp(width)
    return ti


# Colunas da tabela de round: (chave, título, largura em dp)
ROUND_COLUMNS = [
    ("name", "Nome", 110),
    ("time", "Tempo", 65),
    ("landing", "Pouso", 65),
    ("height", "Altura", 65),
    ("landing_over_10", "Pouso >10m", 90),
    ("landing_over_75", "Pouso >75m", 95),
    ("motor_restarted", "Motor Reiniciado", 115),
    ("total_points", "Pontos Totais", 90),
    ("score", "Nota", 65),
]
ROUND_TABLE_WIDTH = sum(w for _, _, w in ROUND_COLUMNS)


class F5JScoringApp(App):
    status_text = StringProperty("")

    def build(self):
        self.store = CompeticaoStore()
        self.view = "fly" if self.store.dados.get("setup_done") else "setup"  # abre na página inicial (Voar), ou Ajustes na 1ª vez
        self.root_layout = BoxLayout(orientation='vertical')
        styled_bg(self.root_layout, BG)
        self.rebuild()
        return self.root_layout

    # ---------- Navegação ----------
    def rebuild(self):
        self.root_layout.clear_widgets()

        content = BoxLayout(orientation='vertical', padding=dp(14), spacing=dp(12))

        title = make_label("Glider Score", size='20sp', bold=True)
        content.add_widget(title)

        if not self.store.dados["setup_done"] or self.view == "setup":
            content.add_widget(self.build_setup())
        elif self.view == "fly":
            content.add_widget(self.build_fly())
        elif self.view == "results":
            content.add_widget(self.build_results())

        self.root_layout.add_widget(content)

        if self.store.dados["setup_done"]:
            self.root_layout.add_widget(self.build_tabbar())

    def build_tabbar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(56), padding=dp(6), spacing=dp(6))
        styled_bg(bar, CARD)

        def tab_btn(label, view_name):
            active = self.view == view_name
            b = make_button(
                label,
                bg=CARD if not active else CARD2,
                color=PRIMARY if active else MUTED,
                height=44,
            )
            b.bind(on_press=lambda *a: self.switch_view(view_name))
            return b

        bar.add_widget(tab_btn("Voar", "fly"))
        bar.add_widget(tab_btn("Resultados", "results"))
        bar.add_widget(tab_btn("Ajustes", "setup"))
        return bar

    def switch_view(self, view_name):
        self.view = view_name
        self.rebuild()

    # ---------- Tela: Setup ----------
    def build_setup(self):
        d = self.store.dados
        wrap = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=1)

        scroll = ScrollView()
        inner = BoxLayout(orientation='vertical', spacing=dp(10), size_hint_y=None, padding=dp(4))
        inner.bind(minimum_height=inner.setter('height'))

        inner.add_widget(make_label("Nome do evento (opcional)", size='12sp', color=MUTED))
        self.input_event_name = make_input(text=d.get("event_name", ""), hint="Ex: Flyoff Brasileiro F5J 2026")
        inner.add_widget(self.input_event_name)

        row = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(10))
        col1 = BoxLayout(orientation='vertical')
        col1.add_widget(make_label("Nº de pilotos", size='12sp', color=MUTED))
        self.input_num_pilotos = make_input(text=str(d["num_pilotos"]), input_filter='int')
        col1.add_widget(self.input_num_pilotos)
        col2 = BoxLayout(orientation='vertical')
        col2.add_widget(make_label("Nº de rounds", size='12sp', color=MUTED))
        self.input_num_rounds = make_input(text=str(d["num_rounds"]), input_filter='int')
        col2.add_widget(self.input_num_rounds)
        row.add_widget(col1)
        row.add_widget(col2)
        inner.add_widget(row)

        self.pilot_inputs_box = BoxLayout(orientation='vertical', spacing=dp(6), size_hint_y=None)
        self.pilot_inputs_box.bind(minimum_height=self.pilot_inputs_box.setter('height'))
        inner.add_widget(self.pilot_inputs_box)

        self.input_num_pilotos.bind(text=lambda *a: self.refresh_pilot_inputs())
        self.refresh_pilot_inputs()

        scroll.add_widget(inner)
        wrap.add_widget(scroll)

        btn_start = make_button(
            "Salvar ajustes" if d["setup_done"] else "Iniciar competição"
        )
        btn_start.bind(on_press=lambda *a: self.start_competicao())
        wrap.add_widget(btn_start)

        if d["setup_done"]:
            btn_reset = make_button("Apagar tudo e recomeçar", bg=DANGER)
            btn_reset.bind(on_press=lambda *a: self.confirmar_reset())
            wrap.add_widget(btn_reset)

        return wrap

    def refresh_pilot_inputs(self):
        try:
            n = max(1, int(self.input_num_pilotos.text or "1"))
        except ValueError:
            n = 1
        n = min(n, 60)

        existentes = [c for c in self.pilot_inputs_box.children[::-1]]
        nomes_atuais = []
        for row in existentes:
            ti = row.children[0]
            nomes_atuais.append(ti.text)

        self.pilot_inputs_box.clear_widgets()
        self.pilot_name_inputs = []
        pilotos_salvos = self.store.dados["pilotos"]

        for i in range(n):
            if i < len(nomes_atuais) and nomes_atuais[i]:
                default_name = nomes_atuais[i]
            elif i < len(pilotos_salvos):
                default_name = pilotos_salvos[i]["name"]
            else:
                default_name = ""

            row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
            row.add_widget(make_label(f"{i + 1}.", size='13sp', color=MUTED))
            ti = make_input(hint=f"Nome do piloto {i + 1}", text=default_name)
            row.add_widget(ti)
            self.pilot_inputs_box.add_widget(row)
            self.pilot_name_inputs.append(ti)

    def start_competicao(self):
        try:
            n = max(1, int(self.input_num_pilotos.text or "1"))
        except ValueError:
            n = 1
        try:
            rounds = max(1, int(self.input_num_rounds.text or "1"))
        except ValueError:
            rounds = 1

        pilotos = []
        for i, ti in enumerate(self.pilot_name_inputs):
            nome = ti.text.strip() or f"Piloto {i + 1}"
            pilotos.append({"name": nome})

        self.store.dados["event_name"] = self.input_event_name.text.strip()
        self.store.dados["num_pilotos"] = n
        self.store.dados["num_rounds"] = rounds
        self.store.dados["pilotos"] = pilotos
        self.store.dados["setup_done"] = True
        if not self.store.dados.get("current_round"):
            self.store.dados["current_round"] = 1
        self.store.salvar()

        self.view = "fly"
        self.rebuild()

    def confirmar_reset(self):
        content = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(12))
        content.add_widget(make_label(
            "Isso vai apagar todos os pilotos e voos registrados. Continuar?",
            size='14sp',
        ))
        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        btn_sim = make_button("Sim", bg=DANGER)
        btn_nao = make_button("Não", bg=CARD2, color=TEXT)
        btn_row.add_widget(btn_sim)
        btn_row.add_widget(btn_nao)
        content.add_widget(btn_row)

        popup = Popup(title="Confirmar", content=content, size_hint=(0.85, 0.35))
        btn_nao.bind(on_press=popup.dismiss)

        def do_reset(*a):
            self.store.resetar()
            self.view = "setup"
            popup.dismiss()
            self.rebuild()

        btn_sim.bind(on_press=do_reset)
        popup.open()

    # ---------- Tela: Fly (registro por round, colunas em inglês) ----------
    def build_fly(self):
        d = self.store.dados
        r = d.get("current_round", 1)
        r = max(1, min(r, d["num_rounds"]))
        d["current_round"] = r
        is_last_round = (r == d["num_rounds"])

        wrap = BoxLayout(orientation='vertical', spacing=dp(10))

        nav = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        btn_prev = make_button("‹", bg=CARD2, height=44)
        btn_prev.size_hint_x = None
        btn_prev.width = dp(44)
        btn_prev.disabled = (r <= 1)
        lbl_round = make_label(f"Round {r} de {d['num_rounds']}", size='16sp', bold=True, halign='center')
        btn_next = make_button("›", bg=CARD2, height=44)
        btn_next.size_hint_x = None
        btn_next.width = dp(44)
        btn_next.disabled = (r >= d["num_rounds"])

        btn_prev.bind(on_press=lambda *a: self.mudar_round(-1))
        btn_next.bind(on_press=lambda *a: self.mudar_round(1))

        nav.add_widget(btn_prev)
        nav.add_widget(lbl_round)
        nav.add_widget(btn_next)
        wrap.add_widget(nav)

        if is_last_round:
            btn_finish = make_button("Finalizar Competição", bg=GOOD, color="#06210f", height=46)
            btn_finish.bind(on_press=lambda *a: self.finalizar_competicao())
            wrap.add_widget(btn_finish)

        # --- Tabela com scroll horizontal (colunas fixas) + vertical (linhas) ---
        outer_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint=(1, 1))
        table_container = BoxLayout(orientation='vertical', size_hint=(None, None),
                                     width=dp(ROUND_TABLE_WIDTH), height=dp(360))

        header = GridLayout(cols=len(ROUND_COLUMNS), size_hint=(None, None),
                             width=dp(ROUND_TABLE_WIDTH), height=dp(30))
        for key, title, w in ROUND_COLUMNS:
            lbl = make_label(title, size='10sp', bold=True, color=MUTED, halign='center')
            lbl.size_hint_x = None
            lbl.width = dp(w)
            header.add_widget(lbl)
        table_container.add_widget(header)

        rows_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, size_hint=(1, 1))
        rows_grid = GridLayout(cols=len(ROUND_COLUMNS), size_hint=(None, None),
                                width=dp(ROUND_TABLE_WIDTH), spacing=dp(2))
        rows_grid.bind(minimum_height=rows_grid.setter('height'))

        flights_round = d["flights"].setdefault(str(r), {})
        self.fly_time_inputs = {}
        self.fly_landing_inputs = {}
        self.fly_height_inputs = {}
        self.fly_lo10_checks = {}
        self.fly_lo75_checks = {}
        self.fly_motor_checks = {}
        self.fly_total_labels = {}
        self.fly_score_labels = {}

        for i, piloto in enumerate(d["pilotos"]):
            flight = flights_round.get(str(i), {})

            name_lbl = make_label(piloto["name"], size='12sp')
            name_lbl.size_hint_x = None
            name_lbl.width = dp(110)
            name_lbl.height = dp(44)
            rows_grid.add_widget(name_lbl)

            ti_time = make_time_input(digits_text=str(flight.get("time", "")), width=65)
            ti_time.height = dp(40)
            rows_grid.add_widget(ti_time)

            ti_landing = make_input(text=str(flight.get("landing", "")), input_filter='float', width=65)
            ti_landing.height = dp(40)
            rows_grid.add_widget(ti_landing)

            ti_height = make_input(text=str(flight.get("height", "")), input_filter='float', width=65)
            ti_height.height = dp(40)
            rows_grid.add_widget(ti_height)

            box_lo10 = BoxLayout(size_hint=(None, None), width=dp(90), height=dp(44))
            cb_lo10 = CheckBox(active=bool(flight.get("landing_over_10", False)))
            box_lo10.add_widget(cb_lo10)
            rows_grid.add_widget(box_lo10)

            box_lo75 = BoxLayout(size_hint=(None, None), width=dp(95), height=dp(44))
            cb_lo75 = CheckBox(active=bool(flight.get("landing_over_75", False)))
            box_lo75.add_widget(cb_lo75)
            rows_grid.add_widget(box_lo75)

            box_motor = BoxLayout(size_hint=(None, None), width=dp(115), height=dp(44))
            cb_motor = CheckBox(active=bool(flight.get("motor_restarted", False)))
            box_motor.add_widget(cb_motor)
            rows_grid.add_widget(box_motor)

            total_lbl = make_label(self._score_display(flight), size='12sp', halign='center')
            total_lbl.size_hint_x = None
            total_lbl.width = dp(90)
            total_lbl.height = dp(44)
            rows_grid.add_widget(total_lbl)

            score_lbl = make_label("–", size='12sp', color=GOLD, halign='center')
            score_lbl.size_hint_x = None
            score_lbl.width = dp(65)
            score_lbl.height = dp(44)
            rows_grid.add_widget(score_lbl)

            self.fly_time_inputs[i] = ti_time
            self.fly_landing_inputs[i] = ti_landing
            self.fly_height_inputs[i] = ti_height
            self.fly_lo10_checks[i] = cb_lo10
            self.fly_lo75_checks[i] = cb_lo75
            self.fly_motor_checks[i] = cb_motor
            self.fly_total_labels[i] = total_lbl
            self.fly_score_labels[i] = score_lbl

            ti_time.bind(text=lambda inst, val, idx=i: self.on_flight_change(idx, 'time', val))
            ti_landing.bind(text=lambda inst, val, idx=i: self.on_flight_change(idx, 'landing', val))
            ti_height.bind(text=lambda inst, val, idx=i: self.on_flight_change(idx, 'height', val))
            cb_lo10.bind(active=lambda inst, val, idx=i: self.on_flight_change(idx, 'landing_over_10', val))
            cb_lo75.bind(active=lambda inst, val, idx=i: self.on_flight_change(idx, 'landing_over_75', val))
            cb_motor.bind(active=lambda inst, val, idx=i: self.on_flight_change(idx, 'motor_restarted', val))

        rows_scroll.add_widget(rows_grid)
        table_container.add_widget(rows_scroll)
        outer_scroll.add_widget(table_container)
        wrap.add_widget(outer_scroll)

        self.refresh_round_scores()
        return wrap

    def _score_display(self, flight):
        if not flight or (flight.get("time", "") in (None, "") and flight.get("landing", "") in (None, "")):
            return "–"
        return f"{raw_score(flight):.1f}"

    def on_flight_change(self, pilot_idx, field, value):
        d = self.store.dados
        r = d["current_round"]
        flights_round = d["flights"].setdefault(str(r), {})
        flight = flights_round.setdefault(str(pilot_idx), {})
        flight[field] = value
        self.store.salvar()
        self.fly_total_labels[pilot_idx].text = self._score_display(flight)
        # a normalização do round pode mudar para todos os pilotos (novo melhor valor)
        self.refresh_round_scores()

    def refresh_round_scores(self):
        r = self.store.dados["current_round"]
        norm = self.store.normalized_round(r)
        for i, lbl in self.fly_score_labels.items():
            lbl.text = f"{norm[i]:.0f}" if norm[i] > 0 else "–"

    def mudar_round(self, delta):
        d = self.store.dados
        novo = d["current_round"] + delta
        novo = max(1, min(novo, d["num_rounds"]))
        d["current_round"] = novo
        self.store.salvar()
        self.rebuild()

    def finalizar_competicao(self):
        self.view = "results"
        self.rebuild()

    # ---------- Tela: Results (estilo GliderScore) ----------
    def build_results(self):
        d = self.store.dados
        linhas = self.store.resultado_geral()

        wrap = BoxLayout(orientation='vertical', spacing=dp(8))

        titulo = d.get("event_name") or "Resultados F5J"
        wrap.add_widget(make_label(titulo, size='16sp', bold=True))
        wrap.add_widget(make_label(
            f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} — Round atual: {d['current_round']} de {d['num_rounds']}",
            size='10sp', color=MUTED,
        ))

        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        btn_pdf = make_button("Exportar PDF", bg=GOOD, color="#06210f", height=44)
        btn_pdf.bind(on_press=lambda *a: self.exportar_pdf())
        btn_new = make_button("Nova Competição", bg=DANGER, height=44)
        btn_new.bind(on_press=lambda *a: self.confirmar_reset())
        btn_row.add_widget(btn_pdf)
        btn_row.add_widget(btn_new)
        wrap.add_widget(btn_row)

        n_cols = 5 + d["num_rounds"]  # Rank, Nome, Score, Pcnt, Raw, Rnd1..RndN
        header = GridLayout(cols=n_cols, size_hint_y=None, height=dp(26))
        for txt in ["Rank", "Nome", "Score", "Pcnt", "Raw"]:
            header.add_widget(make_label(txt, size='11sp', bold=True, color=MUTED, halign='center'))
        for r in range(1, d["num_rounds"] + 1):
            header.add_widget(make_label(f"Rnd{r}", size='11sp', bold=True, color=MUTED, halign='center'))
        wrap.add_widget(header)

        scroll = ScrollView()
        grid = GridLayout(cols=n_cols, size_hint_y=None, spacing=dp(2), row_default_height=dp(34))
        grid.bind(minimum_height=grid.setter('height'))

        for linha in linhas:
            cor_pos = GOLD if linha["rank"] == 1 else TEXT
            grid.add_widget(make_label(str(linha["rank"]), size='13sp', bold=(linha["rank"] == 1), color=cor_pos, halign='center'))
            grid.add_widget(make_label(linha["name"], size='13sp'))
            grid.add_widget(make_label(f"{linha['score']:.1f}", size='12sp', bold=True, halign='center'))
            grid.add_widget(make_label(f"{linha['pcnt']:.2f}", size='12sp', color=MUTED, halign='center'))
            grid.add_widget(make_label(f"{linha['raw']:.1f}", size='12sp', color=MUTED, halign='center'))
            for val in linha["rounds"]:
                txt = f"{val:.1f}" if val > 0 else "0.0"
                grid.add_widget(make_label(txt, size='12sp', halign='center'))

        scroll.add_widget(grid)
        wrap.add_widget(scroll)
        return wrap

    # ---------- Exportação em PDF ----------
    def exportar_pdf(self):
        try:
            from fpdf import FPDF
        except ImportError:
            self.mostrar_aviso(
                "Para exportar em PDF, adicione 'fpdf2' aos requirements do buildozer.spec "
                "(requirements = python3,kivy,fpdf2) e recompile o app."
            )
            return

        d = self.store.dados
        linhas = self.store.resultado_geral()
        titulo = d.get("event_name") or "Resultados F5J"
        num_rounds = d["num_rounds"]

        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, titulo, ln=1, align='C')
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=1, align='C')
        pdf.ln(4)

        headers = ["Rank", "Nome", "Score", "Pcnt", "Raw"] + [f"Rnd{r}" for r in range(1, num_rounds + 1)]
        col_widths = [15, 60, 22, 18, 22] + [18] * num_rounds

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(230, 230, 230)
        for h, w in zip(headers, col_widths):
            pdf.cell(w, 8, h, border=1, align='C', fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 10)
        for linha in linhas:
            valores = [
                str(linha["rank"]),
                linha["name"],
                f"{linha['score']:.1f}",
                f"{linha['pcnt']:.2f}",
                f"{linha['raw']:.1f}",
            ] + [f"{v:.1f}" for v in linha["rounds"]]
            aligns = ['C', 'L', 'C', 'C', 'C'] + ['C'] * num_rounds
            for val, w, al in zip(valores, col_widths, aligns):
                pdf.cell(w, 7, val, border=1, align=al)
            pdf.ln()

        pasta = self.user_data_dir
        nome_arquivo = f"resultados_f5j_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        caminho = os.path.join(pasta, nome_arquivo)
        try:
            pdf.output(caminho)
            self.mostrar_aviso(f"PDF salvo em:\n{caminho}")
        except Exception as e:
            self.mostrar_aviso(f"Erro ao salvar PDF: {e}")

    def mostrar_aviso(self, mensagem):
        content = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(12))
        lbl = make_label(mensagem, size='13sp')
        lbl.size_hint_y = None
        lbl.bind(texture_size=lambda inst, val: setattr(lbl, 'height', val[1] + dp(10)))
        content.add_widget(lbl)
        btn_ok = make_button("OK", height=44)
        content.add_widget(btn_ok)
        popup = Popup(title="Aviso", content=content, size_hint=(0.85, 0.5))
        btn_ok.bind(on_press=popup.dismiss)
        popup.open()

    def on_stop(self):
        self.store.salvar()


if __name__ == '__main__':
    F5JScoringApp().run()
