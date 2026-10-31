"""
Survival Game 3D (single-player) - Panda3D + Bullet

Controles:
  WASD mover | Shift correr | Espaco pular | Mouse olhar | Clique atacar
  E pegar/ler | Tab mochila | 1-4 usar item | F lanterna | J diario
  F5 salvar | F9 carregar | F3 FPS | Esc soltar o mouse | R recomecar (morto)

Para comecar um jogo novo ignorando o save:  python survival_game.py --novo
"""
import json
import os
import random
import sys
import time
from math import atan2, cos, degrees, pi, radians, sin

from direct.gui import DirectGuiGlobals as DGG
from direct.gui.DirectGui import DirectButton, DirectFrame, DirectWaitBar
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.bullet import (BulletBoxShape, BulletCapsuleShape,
                            BulletCharacterControllerNode, BulletRigidBodyNode,
                            BulletWorld, ZUp)
from panda3d.core import (AmbientLight, AntialiasAttrib, ClockObject,
                          DirectionalLight, Fog, Geom, GeomNode, GeomTriangles,
                          GeomVertexData, GeomVertexFormat, GeomVertexWriter,
                          ModifierButtons, NodePath, PerspectiveLens, Point3,
                          Spotlight, TextNode, TransparencyAttrib, Vec3, Vec4,
                          WindowProperties, loadPrcFileData)

loadPrcFileData("", """
window-title Survival Game
win-size 1280 720
framebuffer-multisample 1
multisamples 4
""")

# ---------------------------------------------------------------------------
# Configuracoes (mexa aqui para balancear o jogo)
# ---------------------------------------------------------------------------
TAMANHO_MUNDO = 100            # metade do lado do mapa (200 x 200 m)
DURACAO_DIA = 720.0            # segundos reais para 24h do jogo
HORA_INICIAL = 7.0
POSICAO_INICIAL = (0, 22, 1.2)  # dentro do hospital
SOMBRAS = True                 # sombras do sol (desligue se ficar pesado)

VELOCIDADE_ANDAR = 4.5
VELOCIDADE_CORRIDA = 7.5
ALCANCE_ATAQUE = 2.4
ALCANCE_COLETA = 2.5

TAMANHO_MOCHILA = 12
INTERVALO_AUTOSAVE = 60.0
ARQUIVO_SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savegame.json")

ALCANCE_VISAO_DIA = 10.0
ALCANCE_VISAO_NOITE = 25.0

ITENS = {
    "comida": {"nome": "Lata de comida", "cor": (0.85, 0.55, 0.15, 1), "max": 5, "efeito": {"fome": 35}},
    "agua": {"nome": "Garrafa de agua", "cor": (0.25, 0.55, 0.95, 1), "max": 5, "efeito": {"sede": 40}},
    "kit": {"nome": "Kit medico", "cor": (0.90, 0.15, 0.15, 1), "max": 3, "efeito": {"vida": 40}},
    "bateria": {"nome": "Pilhas", "cor": (0.90, 0.85, 0.20, 1), "max": 4, "efeito": {"bateria": 60}},
}

ITENS_HOSPITAL = [
    ("agua", (-2, 12, 1.4)), ("comida", (2, 12, 1.4)), ("kit", (-10.5, 21, 0.95)),
    ("agua", (8, 20, 0.35)), ("bateria", (9, 28, 0.35)), ("comida", (-8, 30, 0.35)),
]

NOTAS = {
    "recepcao": {
        "titulo": "Recepcao - aviso interno",
        "texto": "Evacuacao geral as 06h. Todos os pacientes foram levados de onibus. "
                 "O leito 4 ficou para tras: ninguem atendeu o radio.",
        "pos": (0, 12, 1.4)},
    "leito": {
        "titulo": "Prontuario do leito 4",
        "texto": "Paciente em coma induzido ha 11 dias. Nome rasurado. "
                 "Se acordar, nao deixe sair depois que escurecer.",
        "pos": (-10.5, 30, 0.95)},
    "farmacia": {
        "titulo": "Receituario - lote 7-B",
        "texto": "Lote experimental distribuido para a cidade inteira. "
                 "Reacao adversa registrada: desorientacao, depois silencio.",
        "pos": (9, 22, 0.35)},
    "carro": {
        "titulo": "Bilhete no painel do carro",
        "texto": "As sirenes pararam todas ao mesmo tempo. Quando olhei em volta, "
                 "a rua estava vazia. Os carros ainda estavam com o motor ligado.",
        "pos": (4, -12, 0.3)},
    "mapa": {
        "titulo": "Mapa rabiscado a mao",
        "texto": "Um abrigo marcado ao norte, depois da floresta. "
                 "Embaixo, em letras tremidas: eles saem quando escurece.",
        "pos": (-22, 55, 0.3)},
}

INTRODUCAO = "Voce acorda no hospital. Esta tudo em silencio... onde foi todo mundo?"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def lerp(a, b, t):
    return a + (b - a) * t


def misturar(cor_a, cor_b, t):
    return tuple(lerp(a, b, t) for a, b in zip(cor_a, cor_b))


def suavizar(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def fora_do_hospital(x, y, folga=20):
    """True se (x, y) esta longe da area do hospital/estacionamento."""
    return not (-folga < x < folga and -folga < y < 40)


def criar_cubo_base():
    """Cubo de -1 a +1 com normais. O tamanho passado em setScale e a metade
    da dimensao, igual ao BulletBoxShape."""
    dados = GeomVertexData("cubo", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vertices = GeomVertexWriter(dados, "vertex")
    normais = GeomVertexWriter(dados, "normal")
    triangulos = GeomTriangles(Geom.UHStatic)

    # (normal, eixo u, eixo v) com u x v = normal
    faces = [
        ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
        ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    ]
    base = 0
    for n, u, v in faces:
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vertices.addData3(*[n[i] + u[i] * su + v[i] * sv for i in range(3)])
            normais.addData3(*n)
        triangulos.addVertices(base, base + 1, base + 2)
        triangulos.addVertices(base, base + 2, base + 3)
        base += 4

    geom = Geom(dados)
    geom.addPrimitive(triangulos)
    no = GeomNode("cubo")
    no.addGeom(geom)
    return NodePath(no)


# ---------------------------------------------------------------------------
# Ciclo de dia e noite
# ---------------------------------------------------------------------------
class CicloDiaNoite:
    CEU_DIA = (0.53, 0.75, 0.92)
    CEU_NOITE = (0.015, 0.02, 0.05)
    CEU_CREPUSCULO = (0.90, 0.45, 0.25)
    SOL_DIA = (1.0, 0.95, 0.82)
    SOL_NOITE = (0.10, 0.12, 0.22)
    AMBIENTE_DIA = (0.42, 0.45, 0.50)
    AMBIENTE_NOITE = (0.05, 0.06, 0.10)

    def __init__(self, jogo):
        self.jogo = jogo
        self.hora = HORA_INICIAL
        self.dia = 1               # o dia vira as 6h da manha
        self.noite = False

        self.ambiente = AmbientLight("ambiente")
        self.ambiente_np = jogo.render.attachNewNode(self.ambiente)
        self.sol = DirectionalLight("sol")
        self.sol_np = jogo.render.attachNewNode(self.sol)
        if SOMBRAS:
            self.sol.setShadowCaster(True, 2048, 2048)
            lente = self.sol.getLens()
            lente.setFilmSize(70, 70)
            lente.setNearFar(1, 140)
        jogo.render.setLight(self.ambiente_np)
        jogo.render.setLight(self.sol_np)

        self.neblina = Fog("neblina")
        jogo.render.setFog(self.neblina)
        self.aplicar()

    @property
    def hora_texto(self):
        return f"{int(self.hora):02d}:{int((self.hora % 1) * 60):02d}"

    def reiniciar(self):
        self.hora = HORA_INICIAL
        self.dia = 1
        self.aplicar()

    def avancar(self, horas):
        """Avanca o relogio do jogo (em horas), contando a virada do dia as 6h."""
        while horas > 0:
            passo = min(horas, 1.0)
            horas -= passo
            antes = self.hora
            self.hora += passo
            if antes < 6.0 <= self.hora:
                self.dia += 1
            if self.hora >= 24.0:
                self.hora -= 24.0

    def atualizar(self, dt):
        self.avancar(dt * 24.0 / DURACAO_DIA)
        self.aplicar()

    def aplicar(self):
        # 1 ao meio-dia, 0 as 6h e 18h, -1 a meia-noite
        altura = sin((self.hora - 6.0) / 24.0 * 2 * pi)
        self.noite = altura < -0.05

        luz = suavizar((altura + 0.1) / 0.35)
        crepusculo = max(0.0, 1.0 - abs(altura) / 0.25)

        ceu = misturar(self.CEU_NOITE, self.CEU_DIA, luz)
        ceu = misturar(ceu, self.CEU_CREPUSCULO, crepusculo * 0.5)

        self.sol.setColor(Vec4(*misturar(self.SOL_NOITE, self.SOL_DIA, luz), 1))
        self.ambiente.setColor(Vec4(*misturar(self.AMBIENTE_NOITE, self.AMBIENTE_DIA, luz), 1))
        self.sol_np.setHpr(self.hora / 24.0 * 360.0, -(25 + 55 * max(altura, 0.0)), 0)

        self.neblina.setColor(*ceu)
        self.neblina.setExpDensity(lerp(0.022, 0.008, luz))
        self.jogo.setBackgroundColor(*ceu, 1)

    def seguir(self, pos):
        """Mantem o 'sol' perto do jogador para as sombras terem boa resolucao."""
        direcao = self.jogo.render.getRelativeVector(self.sol_np, Vec3(0, 1, 0))
        self.sol_np.setPos(pos - direcao * 70)


# ---------------------------------------------------------------------------
# Monstros
# ---------------------------------------------------------------------------
class Monstro:
    def __init__(self, jogo, posicao, nivel):
        self.jogo = jogo
        # Evolucao progressiva: a cada dia que passa eles ficam mais fortes
        self.vida = min(8.0, 3.0 + 0.4 * (nivel - 1))
        self.dano = min(25.0, 10.0 + 1.5 * (nivel - 1))
        self.velocidade = random.uniform(2.4, 3.4) * min(1.5, 1.0 + 0.04 * (nivel - 1))
        self.recarga_ataque = 0.0
        self.atordoado = 0.0
        self.tempo_vagar = 0.0
        self.direcao_vagar = Vec3(0, 0, 0)
        self.fase = 0.0

        forma = BulletCapsuleShape(0.4, 1.0, ZUp)
        self.controle = BulletCharacterControllerNode(forma, 0.4, "monstro")
        self.controle.setGravity(25.0)
        self.no = jogo.render.attachNewNode(self.controle)
        self.no.setPos(posicao)
        jogo.mundo.attachCharacter(self.controle)

        self.visual = self.no.attachNewNode("monstro_visual")
        self.visual.setZ(-0.9)
        self.membros = jogo.criar_humanoide(self.visual,
                                            roupa=(0.35, 0.08, 0.08, 1),
                                            pele=(0.35, 0.50, 0.32, 1),
                                            calca=(0.15, 0.12, 0.12, 1))

    def parar(self):
        self.controle.setLinearMovement(Vec3(0, 0, 0), True)

    def atualizar(self, dt, pos_jogador, noite):
        self.recarga_ataque = max(0.0, self.recarga_ataque - dt)

        if self.atordoado > 0:
            self.atordoado -= dt
            self.parar()
            return

        ate = pos_jogador - self.no.getPos()
        ate.z = 0
        dist = ate.length()
        alcance = ALCANCE_VISAO_NOITE if noite else ALCANCE_VISAO_DIA
        perseguindo = 0.01 < dist < alcance
        andando = False

        if perseguindo:
            direcao = ate / dist
            self.visual.setH(degrees(atan2(-direcao.x, direcao.y)))
            if dist > 1.4:
                bonus = 1.25 if noite else 1.0
                self.controle.setLinearMovement(direcao * self.velocidade * bonus, True)
                andando = True
            else:
                self.parar()
                if self.recarga_ataque <= 0:
                    self.recarga_ataque = 1.3
                    self.jogo.dano_jogador(self.dano)
        else:
            andando = self.vagar(dt)

        self.fase += dt * (9.0 if perseguindo else 5.0)
        self.jogo.animar_membros(self.membros, self.fase, 30 if andando else 0, perseguindo)

    def vagar(self, dt):
        self.tempo_vagar -= dt
        if self.tempo_vagar <= 0:
            self.tempo_vagar = random.uniform(2, 5)
            if random.random() < 0.5:
                self.direcao_vagar = Vec3(0, 0, 0)
            else:
                ang = random.uniform(0, 2 * pi)
                self.direcao_vagar = Vec3(cos(ang), sin(ang), 0)
                self.visual.setH(degrees(atan2(-self.direcao_vagar.x, self.direcao_vagar.y)))
        self.controle.setLinearMovement(self.direcao_vagar, True)
        return self.direcao_vagar.lengthSquared() > 0

    def remover(self):
        self.jogo.mundo.removeCharacter(self.controle)
        self.no.removeNode()


# ---------------------------------------------------------------------------
# Jogo
# ---------------------------------------------------------------------------
class SurvivalGame(ShowBase):
    def __init__(self):
        super().__init__()
        self.disableMouse()
        self.render.setShaderAuto()          # luz e sombras por pixel
        self.render.setAntialias(AntialiasAttrib.MAuto)
        self.camLens.setFov(75)
        self.camLens.setNearFar(0.1, 500)
        # Sem isso, segurar Shift muda o nome do evento ("shift-w" em vez de "w")
        self.buttonThrowers[0].node().setModifierButtons(ModifierButtons())
        self.medidor_fps = True
        self.setFrameRateMeter(True)

        # Estado do jogo
        self.coletaveis = []                 # itens e notas espalhados no mundo
        self.mochila = [None] * TAMANHO_MOCHILA   # cada slot: [id, quantidade]
        self.diario = []                     # ids das notas lidas
        self.monstros = []
        self.tempo_spawn = 5.0
        self.tempo_mensagem = 0.0
        self.tempo_save_msg = 0.0
        self.tempo_autosave = INTERVALO_AUTOSAVE
        self.tempo_janela = 0.0
        self.recarga_ataque = 0.0
        self.flash_dano = 0.0
        self.correndo = False
        self.morto = False
        self.lendo = False
        self.inventario_aberto = False
        self.lanterna_ligada = False
        self.mouse_preso = False
        self.pular_leitura_mouse = 0
        self.fase_andar = 0.0
        self.amp_andar = 0.0
        self.janelas = []
        self.vida = self.fome = self.sede = self.bateria = 100.0

        # Camera
        self.distancia_camera = 6.0
        self.camera_yaw = 180.0              # olhando para a saida do hospital
        self.camera_pitch = 15.0
        self.camera_fracao = 1.0
        self.sensibilidade_mouse = 0.18
        self.rotacao_atual = 180.0

        # Mundo
        self.cubo_base = criar_cubo_base()
        self.cenario = self.render.attachNewNode("cenario")      # colisoes e objetos dinamicos
        self.estatico = self.render.attachNewNode("estatico")    # visual fixo (otimizado)
        self.mundo = BulletWorld()
        self.mundo.setGravity(Vec3(0, 0, -9.81))
        self.ciclo = CicloDiaNoite(self)

        random.seed(7)                       # mesmo mapa sempre
        self.criar_chao_e_limites()
        self.criar_manchas_de_grama()
        self.criar_estrada()
        self.criar_hospital()
        self.criar_arvores(140)
        self.criar_pedras(40)
        self.criar_carros()
        random.seed()                        # volta ao aleatorio (itens, monstros)
        self.estatico.flattenStrong()        # junta o cenario fixo em poucos objetos

        self.criar_jogador()
        self.criar_lanterna()
        self.criar_interface()
        self.configurar_controles()
        self.definir_mouse_preso(True)

        self.ultimo_dia = 1
        if "--novo" not in sys.argv and os.path.exists(ARQUIVO_SAVE) and self.carregar(True):
            pass
        else:
            self.novo_jogo()

        self.taskMgr.add(self.atualizar, "atualizar_jogo")

    # ------------------------------------------------------------------
    # Construcao do mundo
    # ------------------------------------------------------------------
    def criar_bloco(self, nome, posicao, tamanho, cor, colisao=True, visivel=True,
                    dinamico=False):
        """tamanho = metade das dimensoes (igual ao BulletBoxShape)."""
        visual = None
        if visivel:
            visual = self.cubo_base.copyTo(self.cenario if dinamico else self.estatico)
            visual.setPos(*posicao)
            visual.setScale(*tamanho)
            visual.setColor(*cor)

        if colisao:
            corpo = BulletRigidBodyNode(nome)
            corpo.addShape(BulletBoxShape(Vec3(*tamanho)))
            no = self.cenario.attachNewNode(corpo)
            no.setPos(*posicao)
            self.mundo.attachRigidBody(corpo)
        return visual

    def criar_chao_e_limites(self):
        t = TAMANHO_MUNDO
        self.criar_bloco("chao", (0, 0, -0.25), (t, t, 0.25), (0.20, 0.32, 0.20, 1))
        # Paredes invisiveis para ninguem cair do mapa
        for nome, pos, tam in (
            ("limite_n", (0, t, 5), (t, 1, 5)),
            ("limite_s", (0, -t, 5), (t, 1, 5)),
            ("limite_l", (t, 0, 5), (1, t, 5)),
            ("limite_o", (-t, 0, 5), (1, t, 5)),
        ):
            self.criar_bloco(nome, pos, tam, (0, 0, 0, 1), visivel=False)

    def criar_manchas_de_grama(self):
        """Variacao de cor no chao. Uma mancha por celula de 10 m (sem sobreposicao)."""
        for cx in range(-TAMANHO_MUNDO + 5, TAMANHO_MUNDO, 10):
            for cy in range(-TAMANHO_MUNDO + 5, TAMANHO_MUNDO, 10):
                if random.random() > 0.45:
                    continue
                if abs(cx) < 26 and -16 < cy < 42:        # hospital
                    continue
                if abs(cx) < 8 and cy < -10:              # estrada
                    continue
                g = random.uniform(-0.05, 0.05)
                self.criar_bloco("mancha",
                                 (cx + random.uniform(-1, 1), cy + random.uniform(-1, 1), 0.01),
                                 (random.uniform(2, 4), random.uniform(2, 4), 0.01),
                                 (0.20 + g, 0.32 + g * 1.5, 0.20 + g, 1), colisao=False)

    def criar_estrada(self):
        t = TAMANHO_MUNDO
        meio = -(t + 12) / 2
        meia = (t - 12) / 2
        self.criar_bloco("estrada", (0, meio, 0.02), (5, meia, 0.02), (0.20, 0.21, 0.22, 1))

    def criar_hospital(self):
        parede = (0.72, 0.74, 0.72, 1)
        interna = (0.80, 0.82, 0.80, 1)

        # Estacionamento e piso interno
        self.criar_bloco("estacionamento", (0, -2, 0.02), (22, 10, 0.02), (0.28, 0.29, 0.30, 1))
        self.criar_bloco("piso", (0, 20, 0.04), (11.8, 11.8, 0.04), (0.60, 0.62, 0.60, 1))

        # Paredes externas
        self.criar_bloco("parede_esquerda", (-12, 20, 4), (0.5, 12, 4), parede)
        self.criar_bloco("parede_direita", (12, 20, 4), (0.5, 12, 4), parede)
        self.criar_bloco("parede_fundos", (0, 32, 4), (12, 0.5, 4), parede)

        # Fachada com espaco para a entrada (x de -2 a 2)
        self.criar_bloco("fachada_esquerda", (-7, 8, 4), (5, 0.5, 4), parede)
        self.criar_bloco("fachada_direita", (7, 8, 4), (5, 0.5, 4), parede)
        self.criar_bloco("fachada_superior", (0, 8, 7.3), (2, 0.5, 0.7), parede)

        # Telhado
        self.criar_bloco("telhado", (0, 20, 8.2), (12.5, 12.5, 0.3), (0.35, 0.36, 0.37, 1))

        # Divisorias internas: corredor central + quarto (esq) + farmacia (dir)
        for lado in (-1, 1):
            x = lado * 5
            self.criar_bloco("divisoria", (x, 17, 3.95), (0.25, 3, 3.95), interna)
            self.criar_bloco("divisoria", (x, 27.75, 3.95), (0.25, 3.75, 3.95), interna)

        # Recepcao, camas e prateleiras
        self.criar_bloco("balcao", (0, 12, 0.6), (3, 0.6, 0.6), (0.45, 0.35, 0.25, 1))
        for y in (16, 21, 26, 30):
            self.criar_bloco("cama", (-10.5, y, 0.35), (0.9, 1.0, 0.35), (0.85, 0.88, 0.90, 1))
        for y in (17, 27):
            self.criar_bloco("prateleira", (11, y, 1.2), (0.4, 1.5, 1.2), (0.50, 0.48, 0.45, 1))

        # Janelas (brilham de noite) - ficam no grupo dinamico para mudar de cor
        for x in (-9, -5, 5, 9):
            janela = self.criar_bloco("janela", (x, 7.45, 4.8), (1.1, 0.08, 1.2),
                                      (0.12, 0.20, 0.24, 1), colisao=False, dinamico=True)
            janela.setLightOff(1)
            self.janelas.append(janela)

        # Placa e cruz (so visual)
        self.criar_bloco("placa", (0, 7.35, 7.0), (2.5, 0.12, 0.45), (0.10, 0.30, 0.20, 1), False)
        self.criar_bloco("cruz_v", (0, 7.18, 7.0), (0.12, 0.05, 0.32), (0.9, 0.9, 0.9, 1), False)
        self.criar_bloco("cruz_h", (0, 7.17, 7.0), (0.32, 0.05, 0.12), (0.9, 0.9, 0.9, 1), False)

    def criar_arvores(self, quantidade):
        limite = TAMANHO_MUNDO - 6
        criadas = 0
        while criadas < quantidade:
            x = random.uniform(-limite, limite)
            y = random.uniform(-limite, limite)
            if not fora_do_hospital(x, y) or (abs(x) < 7 and y < -10):   # hospital e estrada
                continue
            altura = random.uniform(1.4, 2.4)
            verde = random.uniform(-0.04, 0.05)
            self.criar_bloco("tronco", (x, y, altura), (0.3, 0.3, altura), (0.35, 0.22, 0.12, 1))
            self.criar_bloco("copa_baixa", (x, y, altura * 2 + 0.5), (1.4, 1.4, 0.6),
                             (0.10 + verde, 0.30 + verde, 0.12, 1), colisao=False)
            self.criar_bloco("copa_alta", (x, y, altura * 2 + 1.4), (0.9, 0.9, 0.5),
                             (0.12 + verde, 0.34 + verde, 0.14, 1), colisao=False)
            criadas += 1

    def criar_pedras(self, quantidade):
        limite = TAMANHO_MUNDO - 6
        criadas = 0
        while criadas < quantidade:
            x = random.uniform(-limite, limite)
            y = random.uniform(-limite, limite)
            if not fora_do_hospital(x, y) or (abs(x) < 7 and y < -10):
                continue
            t = random.uniform(0.4, 1.2)
            cinza = random.uniform(0.38, 0.52)
            self.criar_bloco("pedra", (x, y, t * 0.6), (t * 1.2, t, t * 0.6),
                             (cinza, cinza, cinza + 0.03, 1))
            criadas += 1

    def criar_carros(self):
        for x, y, cor in ((-8, -4, (0.45, 0.15, 0.12, 1)),
                          (6, -7, (0.20, 0.30, 0.45, 1)),
                          (-2, -10, (0.50, 0.50, 0.45, 1))):
            self.criar_bloco("carro", (x, y, 0.65), (1.0, 2.1, 0.45), cor)
            self.criar_bloco("cabine", (x, y, 1.45), (0.9, 1.1, 0.4), (0.15, 0.17, 0.20, 1), False)

    def criar_humanoide(self, pai, roupa, pele, calca):
        """Boneco com os pes em z=0 e a frente para +Y. Retorna os membros
        (pivos no quadril e no ombro) para animar."""
        def parte(no_pai, pos, tam, cor):
            n = self.cubo_base.copyTo(no_pai)
            n.setPos(*pos)
            n.setScale(*tam)
            n.setColor(*cor)

        parte(pai, (0, 0, 1.10), (0.32, 0.20, 0.40), roupa)                 # tronco
        parte(pai, (0, 0, 1.65), (0.20, 0.20, 0.20), pele)                  # cabeca
        parte(pai, (0, 0.20, 1.68), (0.14, 0.03, 0.05), (0.05, 0.05, 0.05, 1))   # rosto

        pernas, bracos = [], []
        for lado in (-1, 1):
            perna = pai.attachNewNode("perna")
            perna.setPos(lado * 0.15, 0, 0.80)
            parte(perna, (0, 0, -0.40), (0.13, 0.14, 0.40), calca)
            pernas.append(perna)

            braco = pai.attachNewNode("braco")
            braco.setPos(lado * 0.46, 0, 1.48)
            parte(braco, (0, 0, -0.38), (0.10, 0.12, 0.38), pele)
            bracos.append(braco)
        return {"pernas": pernas, "bracos": bracos}

    @staticmethod
    def animar_membros(membros, fase, amplitude, bracos_frente=False):
        s = sin(fase) * amplitude
        membros["pernas"][0].setP(s)
        membros["pernas"][1].setP(-s)
        if bracos_frente:
            for braco in membros["bracos"]:
                braco.setP(75)
        else:
            membros["bracos"][0].setP(-s * 0.8)
            membros["bracos"][1].setP(s * 0.8)

    def atualizar_janelas(self, dt):
        self.tempo_janela -= dt
        if self.tempo_janela > 0:
            return
        self.tempo_janela = 0.12
        for i, janela in enumerate(self.janelas):
            if self.ciclo.noite and i == 1:        # uma janela acesa: misterio
                brilho = random.uniform(0.5, 1.0) if random.random() < 0.9 else 0.1
                janela.setColor(0.9 * brilho, 0.75 * brilho, 0.35 * brilho, 1)
            else:
                janela.setColor(0.12, 0.20, 0.24, 1)

    # ------------------------------------------------------------------
    # Itens e notas no mundo
    # ------------------------------------------------------------------
    def criar_coletavel(self, tipo, ident, posicao, qtd=1):
        visual = self.cubo_base.copyTo(self.cenario)
        visual.setPos(*posicao)
        if tipo == "item":
            visual.setScale(0.18)
            visual.setColor(*ITENS[ident]["cor"])
        else:
            visual.setScale(0.22, 0.16, 0.03)
            visual.setColor(0.95, 0.92, 0.75, 1)
        self.coletaveis.append({"no": visual, "tipo": tipo, "id": ident, "qtd": qtd})

    def limpar_coletaveis(self):
        for c in self.coletaveis:
            c["no"].removeNode()
        self.coletaveis = []

    def criar_coletaveis_iniciais(self):
        for ident, pos in ITENS_HOSPITAL:
            self.criar_coletavel("item", ident, pos)
        for ident, nota in NOTAS.items():
            self.criar_coletavel("nota", ident, nota["pos"])
        self.espalhar_itens(30)

    def espalhar_itens(self, quantidade):
        limite = TAMANHO_MUNDO - 6
        pesos = [3, 3, 1, 2]                      # comida, agua, kit, pilhas
        criados = 0
        while criados < quantidade:
            x = random.uniform(-limite, limite)
            y = random.uniform(-limite, limite)
            if not fora_do_hospital(x, y):
                continue
            ident = random.choices(list(ITENS), weights=pesos)[0]
            self.criar_coletavel("item", ident, (x, y, 0.3))
            criados += 1

    def item_proximo(self):
        pos = self.jogador.getPos()
        melhor, menor = None, ALCANCE_COLETA
        for c in self.coletaveis:
            d = (c["no"].getPos() - pos).length()
            if d < menor:
                melhor, menor = c, d
        return melhor

    def coletar(self):
        if self.lendo:
            self.fechar_leitura()
            return
        if self.morto or self.inventario_aberto:
            return
        c = self.item_proximo()
        if not c:
            return

        if c["tipo"] == "nota":
            if c["id"] not in self.diario:
                self.diario.append(c["id"])
            c["no"].removeNode()
            self.coletaveis.remove(c)
            nota = NOTAS[c["id"]]
            self.abrir_leitura(f"{nota['titulo']}\n\n{nota['texto']}\n\n[E] fechar   [J] diario")
            return

        restante = self.adicionar_item(c["id"], c["qtd"])
        nome = ITENS[c["id"]]["nome"]
        if restante == c["qtd"]:
            self.mostrar_mensagem("Mochila cheia! (Tab para abrir)", 2.5)
            return
        if restante > 0:
            c["qtd"] = restante
            self.mostrar_mensagem(f"Pegou parte de: {nome} (mochila cheia)", 2.5)
        else:
            c["no"].removeNode()
            self.coletaveis.remove(c)
            self.mostrar_mensagem(f"Pegou: {nome}", 2)

    # ------------------------------------------------------------------
    # Mochila
    # ------------------------------------------------------------------
    def adicionar_item(self, ident, qtd):
        """Retorna quantos itens NAO couberam na mochila."""
        maximo = ITENS[ident]["max"]
        for slot in self.mochila:
            if qtd > 0 and slot and slot[0] == ident and slot[1] < maximo:
                mover = min(qtd, maximo - slot[1])
                slot[1] += mover
                qtd -= mover
        for i, slot in enumerate(self.mochila):
            if qtd <= 0:
                break
            if slot is None:
                mover = min(qtd, maximo)
                self.mochila[i] = [ident, mover]
                qtd -= mover
        self.mochila_mudou()
        return qtd

    def usar_slot(self, i):
        if self.morto:
            return
        slot = self.mochila[i]
        if not slot:
            return
        dados = ITENS[slot[0]]
        efeito = dados["efeito"]
        if all(getattr(self, k) >= 99 for k in efeito):
            self.mostrar_mensagem("Voce nao precisa disso agora.", 2)
            return
        for k, v in efeito.items():
            setattr(self, k, min(100.0, getattr(self, k) + v))
        slot[1] -= 1
        if slot[1] <= 0:
            self.mochila[i] = None
        self.mochila_mudou()
        self.mostrar_mensagem(f"Usou: {dados['nome']}", 2)

    def descartar_slot(self, i, evento=None):
        slot = self.mochila[i]
        if not slot or self.morto:
            return
        h = radians(self.rotacao_atual)
        pos = self.jogador.getPos() + Vec3(-sin(h), cos(h), 0) * 1.5
        self.criar_coletavel("item", slot[0], (pos.x, pos.y, self.jogador.getZ() - 0.6), slot[1])
        self.mochila[i] = None
        self.mochila_mudou()

    def mochila_mudou(self):
        if hasattr(self, "botoes_inv"):
            self.atualizar_mochila_ui()

    def alternar_mochila(self):
        if self.morto:
            return
        self.inventario_aberto = not self.inventario_aberto
        if self.inventario_aberto:
            self.atualizar_mochila_ui()
            self.painel_inv.show()
        else:
            self.painel_inv.hide()
        self.definir_mouse_preso(not self.inventario_aberto)

    # ------------------------------------------------------------------
    # Jogador
    # ------------------------------------------------------------------
    def criar_jogador(self):
        # Capsula: raio 0.4 + cilindro 1.0 = 1.8 m de altura total
        forma = BulletCapsuleShape(0.4, 1.0, ZUp)
        self.controle = BulletCharacterControllerNode(forma, 0.4, "jogador")
        self.controle.setGravity(25.0)
        self.controle.setJumpSpeed(7.5)
        self.controle.setMaxJumpHeight(1.1)
        self.jogador = self.render.attachNewNode(self.controle)
        self.jogador.setPos(*POSICAO_INICIAL)
        self.mundo.attachCharacter(self.controle)

        # O centro da capsula fica a 0.9 m do chao
        self.visual = self.jogador.attachNewNode("jogador_visual")
        self.visual.setZ(-0.9)
        self.visual.setH(self.rotacao_atual)
        self.membros = self.criar_humanoide(self.visual,
                                            roupa=(0.16, 0.28, 0.55, 1),
                                            pele=(0.78, 0.60, 0.46, 1),
                                            calca=(0.12, 0.12, 0.16, 1))

    def criar_lanterna(self):
        self.lanterna = Spotlight("lanterna")
        lente = PerspectiveLens()
        lente.setFov(45)
        self.lanterna.setLens(lente)
        self.lanterna.setColor(Vec4(1.3, 1.2, 1.0, 1))
        self.lanterna.setAttenuation(Vec3(1, 0.0, 0.002))
        self.lanterna_np = self.camera.attachNewNode(self.lanterna)

    def alternar_lanterna(self):
        if not self.lanterna_ligada and self.bateria <= 0:
            self.mostrar_mensagem("Sem pilhas! Procure pilhas pelo mapa.", 2.5)
            return
        self.lanterna_ligada = not self.lanterna_ligada
        if self.lanterna_ligada:
            self.render.setLight(self.lanterna_np)
        else:
            self.render.clearLight(self.lanterna_np)

    def resetar_status(self):
        self.vida = self.fome = self.sede = self.bateria = 100.0
        if self.lanterna_ligada:
            self.alternar_lanterna()

    def mover_jogador(self, dt):
        x = int(self.teclas["direita"]) - int(self.teclas["esquerda"])
        y = int(self.teclas["frente"]) - int(self.teclas["tras"])

        h = radians(self.camera_yaw)
        frente = Vec3(-sin(h), cos(h), 0)
        direita = Vec3(cos(h), sin(h), 0)
        direcao = frente * y + direita * x

        andando = direcao.lengthSquared() > 0
        self.correndo = self.teclas["correr"] and andando
        velocidade = VELOCIDADE_CORRIDA if self.correndo else VELOCIDADE_ANDAR

        if andando:
            direcao.normalize()
            alvo = degrees(atan2(-direcao.x, direcao.y))
            diferenca = (alvo - self.rotacao_atual + 180) % 360 - 180
            self.rotacao_atual += diferenca * min(1.0, 12.0 * dt)
            self.visual.setH(self.rotacao_atual)

        # Animacao dos membros
        self.fase_andar += dt * (11.0 if self.correndo else 7.5)
        alvo_amp = (45.0 if self.correndo else 30.0) if andando else 0.0
        self.amp_andar += (alvo_amp - self.amp_andar) * min(1.0, 10.0 * dt)
        self.animar_membros(self.membros, self.fase_andar, self.amp_andar)

        self.controle.setLinearMovement(direcao * velocidade, True)

    def pular(self):
        if not self.morto and self.controle.isOnGround():
            self.controle.doJump()

    def atacar(self):
        if self.inventario_aberto or self.lendo:
            return
        if not self.mouse_preso:          # primeiro clique recaptura o mouse
            self.definir_mouse_preso(True)
            return
        if self.morto or self.recarga_ataque > 0:
            return
        self.recarga_ataque = 0.5

        h = radians(self.camera_yaw)
        frente = Vec3(-sin(h), cos(h), 0)
        self.rotacao_atual = self.camera_yaw
        self.visual.setH(self.camera_yaw)

        pos = self.jogador.getPos()
        for monstro in list(self.monstros):
            ate = monstro.no.getPos() - pos
            ate.z = 0
            dist = ate.length()
            if dist < ALCANCE_ATAQUE and (dist < 0.8 or frente.dot(ate / dist) > 0.4):
                monstro.vida -= 1.0
                monstro.atordoado = 0.4
                if monstro.vida <= 0:
                    monstro.remover()
                    self.monstros.remove(monstro)
                    self.mostrar_mensagem("Monstro derrotado!", 2)

    def dano_jogador(self, valor, efeito=True):
        if self.morto:
            return
        self.vida = max(0.0, self.vida - valor)
        if efeito:
            self.flash_dano = 0.4
        if self.vida <= 0:
            self.morrer()

    def morrer(self):
        self.morto = True
        self.controle.setLinearMovement(Vec3(0, 0, 0), True)
        if self.inventario_aberto:
            self.alternar_mochila()
        self.fechar_leitura()
        existe_save = os.path.exists(ARQUIVO_SAVE)
        acao = "continuar do ultimo salvamento" if existe_save else "recomecar"
        self.texto_morte.setText(f"VOCE MORREU\nPressione R para {acao}")

    def reiniciar(self):
        if not self.morto:
            return
        if os.path.exists(ARQUIVO_SAVE) and self.carregar(False):
            self.mostrar_mensagem("Voce voltou ao ultimo salvamento.", 4)
        else:
            self.novo_jogo()

    def atualizar_sobrevivencia(self, dt):
        gasto = 1.8 if self.correndo else 1.0
        self.fome = max(0.0, self.fome - 0.10 * gasto * dt)
        self.sede = max(0.0, self.sede - 0.15 * gasto * dt)

        if self.fome <= 0 or self.sede <= 0:
            self.dano_jogador(1.5 * dt, efeito=False)
        elif self.fome > 50 and self.sede > 50:
            self.vida = min(100.0, self.vida + 0.5 * dt)

        if self.lanterna_ligada:
            self.bateria = max(0.0, self.bateria - 0.4 * dt)
            if self.bateria <= 0:
                self.alternar_lanterna()
                self.mostrar_mensagem("As pilhas da lanterna acabaram!", 3)

    # ------------------------------------------------------------------
    # Novo jogo, dias e escassez
    # ------------------------------------------------------------------
    def limpar_monstros(self):
        for monstro in self.monstros:
            monstro.remover()
        self.monstros = []

    def novo_jogo(self):
        self.morto = False
        self.texto_morte.setText("")
        self.fechar_leitura()
        self.resetar_status()
        self.jogador.setPos(*POSICAO_INICIAL)
        self.camera_yaw = 180.0
        self.rotacao_atual = 180.0
        self.visual.setH(180.0)
        self.mochila = [None] * TAMANHO_MOCHILA
        self.mochila_mudou()
        self.diario = []
        self.limpar_monstros()
        self.limpar_coletaveis()
        self.criar_coletaveis_iniciais()
        self.ciclo.reiniciar()
        self.ultimo_dia = self.ciclo.dia
        self.tempo_autosave = INTERVALO_AUTOSAVE
        self.mostrar_mensagem(INTRODUCAO, 8)

    def novo_dia(self):
        dia = self.ciclo.dia
        quantidade = max(4, 18 - 3 * dia)        # escassez progressiva
        self.espalhar_itens(quantidade)
        self.mostrar_mensagem(f"Dia {dia}. Os recursos estao ficando mais escassos...", 5)

    # ------------------------------------------------------------------
    # Salvamento
    # ------------------------------------------------------------------
    def salvar(self, auto=False):
        if self.morto:
            return
        pos = self.jogador.getPos()
        dados = {
            "versao": 1,
            "timestamp": time.time(),
            "jogador": {"pos": [pos.x, pos.y, pos.z], "yaw": self.camera_yaw},
            "status": {"vida": self.vida, "fome": self.fome, "sede": self.sede,
                       "bateria": self.bateria},
            "tempo": {"hora": self.ciclo.hora, "dia": self.ciclo.dia},
            "mochila": self.mochila,
            "diario": self.diario,
            "coletaveis": [
                {"tipo": c["tipo"], "id": c["id"], "qtd": c["qtd"],
                 "pos": list(c["no"].getPos())}
                for c in self.coletaveis
            ],
        }
        try:
            temporario = ARQUIVO_SAVE + ".tmp"
            with open(temporario, "w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, indent=1)
            os.replace(temporario, ARQUIVO_SAVE)
            self.texto_save.setText("Salvo automaticamente" if auto else "Jogo salvo")
            self.tempo_save_msg = 2.0
        except OSError as erro:
            self.mostrar_mensagem(f"Falha ao salvar: {erro}", 4)

    def carregar(self, simular_ausencia=True):
        """Carrega o save. Retorna True se deu certo."""
        try:
            with open(ARQUIVO_SAVE, encoding="utf-8") as arquivo:
                d = json.load(arquivo)
            pos = [float(v) for v in d["jogador"]["pos"]]
            yaw = float(d["jogador"]["yaw"])
            status = {k: float(d["status"][k]) for k in ("vida", "fome", "sede", "bateria")}
            hora = float(d["tempo"]["hora"])
            dia = int(d["tempo"]["dia"])
            mochila = [[s[0], int(s[1])] if s and s[0] in ITENS else None
                       for s in d["mochila"]][:TAMANHO_MOCHILA]
            mochila += [None] * (TAMANHO_MOCHILA - len(mochila))
            diario = [i for i in d["diario"] if i in NOTAS]
            coletaveis = []
            for c in d["coletaveis"]:
                valido = ITENS if c["tipo"] == "item" else NOTAS
                if c["id"] in valido:
                    coletaveis.append((c["tipo"], c["id"], tuple(float(v) for v in c["pos"]),
                                       int(c["qtd"])))
            timestamp = float(d.get("timestamp", time.time()))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as erro:
            self.mostrar_mensagem("Nao foi possivel ler o save. Iniciando jogo novo.", 4)
            print("Erro ao carregar save:", erro)
            return False

        self.morto = False
        self.texto_morte.setText("")
        self.fechar_leitura()
        if self.lanterna_ligada:
            self.alternar_lanterna()
        self.jogador.setPos(*pos)
        self.camera_yaw = yaw
        self.rotacao_atual = yaw
        self.visual.setH(yaw)
        self.camera_fracao = 1.0
        self.vida, self.fome = status["vida"], status["fome"]
        self.sede, self.bateria = status["sede"], status["bateria"]
        self.ciclo.hora = hora
        self.ciclo.dia = dia
        self.mochila = mochila
        self.mochila_mudou()
        self.diario = diario
        self.limpar_monstros()
        self.limpar_coletaveis()
        for tipo, ident, p, qtd in coletaveis:
            self.criar_coletavel(tipo, ident, p, qtd)

        # O mundo continua enquanto voce esta fora (limitado para nao ser injusto)
        mensagem = "Jogo carregado."
        segundos = max(0.0, min(time.time() - timestamp, 1800.0))
        if simular_ausencia and segundos >= 60:
            self.ciclo.avancar(min(segundos / DURACAO_DIA * 24.0, 10.0))
            perda = min(segundos, 600.0)
            self.fome = max(15.0, self.fome - 0.03 * perda)
            self.sede = max(15.0, self.sede - 0.045 * perda)
            mensagem = f"Voce ficou fora por {int(segundos // 60)} min. O mundo seguiu sem voce."
        self.ciclo.aplicar()
        self.ultimo_dia = self.ciclo.dia
        self.tempo_autosave = INTERVALO_AUTOSAVE
        self.mostrar_mensagem(mensagem, 5)
        return True

    # ------------------------------------------------------------------
    # Monstros
    # ------------------------------------------------------------------
    def gerar_monstro(self, pos_jogador):
        limite = TAMANHO_MUNDO - 4
        for _ in range(10):
            ang = random.uniform(0, 2 * pi)
            dist = random.uniform(30, 45)
            x = pos_jogador.x + cos(ang) * dist
            y = pos_jogador.y + sin(ang) * dist
            if abs(x) > limite or abs(y) > limite:
                continue
            if -13 < x < 13 and 6 < y < 34:       # nao nascer dentro do hospital
                continue
            self.monstros.append(Monstro(self, Point3(x, y, 1.5), self.ciclo.dia))
            return

    def gerenciar_monstros(self, dt, pos):
        maximo = min(12, 5 + self.ciclo.dia)
        self.tempo_spawn -= dt
        if (self.ciclo.noite and not self.morto and self.tempo_spawn <= 0
                and len(self.monstros) < maximo):
            self.tempo_spawn = random.uniform(4, 9)
            self.gerar_monstro(pos)

        for monstro in list(self.monstros):
            if not self.ciclo.noite:
                monstro.vida -= 0.3 * dt          # a luz do dia enfraquece os monstros
            if monstro.vida <= 0 or (monstro.no.getPos() - pos).length() > 90:
                monstro.remover()
                self.monstros.remove(monstro)
                continue
            monstro.atualizar(dt, pos, self.ciclo.noite)

    # ------------------------------------------------------------------
    # Camera e mouse
    # ------------------------------------------------------------------
    def definir_mouse_preso(self, preso):
        self.mouse_preso = preso
        props = WindowProperties()
        props.setCursorHidden(preso)
        self.win.requestProperties(props)
        self.pular_leitura_mouse = 3

    def alternar_mouse(self):
        if self.inventario_aberto:
            self.alternar_mochila()
        else:
            self.definir_mouse_preso(not self.mouse_preso)

    def ler_mouse(self):
        if not self.mouse_preso or not self.win.getProperties().getForeground():
            return
        cx, cy = self.win.getXSize() // 2, self.win.getYSize() // 2
        ponteiro = self.win.getPointer(0)
        if self.pular_leitura_mouse > 0:
            self.pular_leitura_mouse -= 1
        else:
            dx = ponteiro.getX() - cx
            dy = ponteiro.getY() - cy
            self.camera_yaw -= dx * self.sensibilidade_mouse
            self.camera_pitch = max(-5.0, min(60.0, self.camera_pitch + dy * self.sensibilidade_mouse))
        self.win.movePointer(0, cx, cy)

    def atualizar_camera(self, pos, dt):
        h, p = radians(self.camera_yaw), radians(self.camera_pitch)
        d = self.distancia_camera
        alvo = Point3(pos.x, pos.y, pos.z + 0.7)
        desejada = Point3(alvo.x + sin(h) * cos(p) * d,
                          alvo.y - cos(h) * cos(p) * d,
                          alvo.z + sin(p) * d)

        # Camera nao atravessa paredes: lanca um raio do jogador ate a camera
        menor = 1.0
        for hit in self.mundo.rayTestAll(alvo, desejada).getHits():
            if hit.getNode().getName() in ("jogador", "monstro"):
                continue
            menor = min(menor, hit.getHitFraction())
        fracao = max(0.1, menor - 0.3 / d)

        if fracao < self.camera_fracao:
            self.camera_fracao = fracao                   # encosta na hora
        else:
            self.camera_fracao += (fracao - self.camera_fracao) * min(1.0, 6.0 * dt)

        self.camera.setPos(alvo + (desejada - alvo) * self.camera_fracao)
        self.camera.lookAt(alvo)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------
    def criar_barra(self, rotulo, indice, cor):
        z = -0.08 - indice * 0.07
        OnscreenText(text=rotulo, parent=self.a2dTopLeft, pos=(0.06, z - 0.012),
                     scale=0.045, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
                     align=TextNode.ALeft, mayChange=False)
        return DirectWaitBar(parent=self.a2dTopLeft, text="", value=100, range=100,
                             pos=(0.52, 0, z), frameSize=(-0.35, 0.35, -0.018, 0.018),
                             barColor=cor, frameColor=(0, 0, 0, 0.5))

    def criar_interface(self):
        self.barra_vida = self.criar_barra("Vida", 0, (0.80, 0.15, 0.15, 1))
        self.barra_fome = self.criar_barra("Fome", 1, (0.90, 0.60, 0.15, 1))
        self.barra_sede = self.criar_barra("Sede", 2, (0.25, 0.55, 0.95, 1))
        self.barra_pilha = self.criar_barra("Pilha", 3, (0.90, 0.85, 0.20, 1))

        estilo = dict(fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1), mayChange=True)
        self.texto_tempo = OnscreenText(parent=self.a2dTopRight, pos=(-0.06, -0.09),
                                        scale=0.06, align=TextNode.ARight, **estilo)
        self.texto_save = OnscreenText(parent=self.a2dTopRight, pos=(-0.06, -0.15),
                                       scale=0.04, align=TextNode.ARight, **estilo)
        self.texto_mensagem = OnscreenText(parent=self.a2dBottomCenter, pos=(0, 0.22),
                                           scale=0.055, wordwrap=40, **estilo)
        self.texto_dica = OnscreenText(parent=self.a2dBottomCenter, pos=(0, 0.35),
                                       scale=0.055, **estilo)
        self.texto_morte = OnscreenText(pos=(0, 0.1), scale=0.1,
                                        fg=(0.9, 0.1, 0.1, 1), shadow=(0, 0, 0, 1),
                                        mayChange=True)
        OnscreenText(text="+", pos=(0, -0.02), scale=0.07, fg=(1, 1, 1, 0.6), mayChange=False)
        OnscreenText(text="WASD mover | Shift correr | Espaco pular | Clique atacar | E pegar/ler\n"
                          "Tab mochila | 1-4 usar | F lanterna | J diario | F5 salvar | F9 carregar",
                     parent=self.a2dTopCenter, pos=(0, -0.05), scale=0.032, wordwrap=50,
                     fg=(1, 1, 1, 0.7), mayChange=False)

        # Barra de atalhos (1-4)
        self.hotbar = []
        for i in range(4):
            quadro = DirectFrame(parent=self.a2dBottomCenter, pos=((i - 1.5) * 0.48, 0, 0.07),
                                 frameSize=(-0.22, 0.22, -0.04, 0.04),
                                 frameColor=(0, 0, 0, 0.5), text="", text_scale=0.032,
                                 text_fg=(1, 1, 1, 1), text_pos=(0, -0.01))
            self.hotbar.append(quadro)

        self.criar_painel_mochila()

        self.painel_leitura = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0.82),
                                          frameSize=(-1.1, 1.1, -0.8, 0.8), text="",
                                          text_scale=0.045, text_wordwrap=46,
                                          text_fg=(1, 1, 1, 1), text_align=TextNode.ALeft,
                                          text_pos=(-1.0, 0.68))
        self.painel_leitura.hide()

        self.overlay_dano = DirectFrame(parent=self.render2d, frameColor=(0.7, 0, 0, 0),
                                        frameSize=(-1, 1, -1, 1))
        self.overlay_dano.setTransparency(TransparencyAttrib.MAlpha)

    def criar_painel_mochila(self):
        self.painel_inv = DirectFrame(parent=self.aspect2d, frameColor=(0, 0, 0, 0.78),
                                      frameSize=(-0.8, 0.8, -0.6, 0.6), text="MOCHILA",
                                      text_scale=0.07, text_pos=(0, 0.5),
                                      text_fg=(1, 1, 1, 1))
        OnscreenText(text="Clique: usar  |  Botao direito: descartar  |  Tab: fechar",
                     parent=self.painel_inv, pos=(0, -0.54), scale=0.036,
                     fg=(1, 1, 1, 0.8), mayChange=False)
        self.botoes_inv = []
        for i in range(TAMANHO_MOCHILA):
            col, lin = i % 4, i // 4
            botao = DirectButton(parent=self.painel_inv,
                                 pos=(-0.54 + col * 0.36, 0, 0.25 - lin * 0.26),
                                 frameSize=(-0.165, 0.165, -0.1, 0.1),
                                 frameColor=(0.2, 0.2, 0.2, 0.85), relief=DGG.FLAT,
                                 text="", text_scale=0.036, text_fg=(1, 1, 1, 1),
                                 text_pos=(0, 0.02), command=self.usar_slot, extraArgs=[i])
            botao.bind(DGG.B3PRESS, self.descartar_slot, [i])
            self.botoes_inv.append(botao)
        self.painel_inv.hide()

    def atualizar_mochila_ui(self):
        for i, botao in enumerate(self.botoes_inv):
            slot = self.mochila[i]
            if slot:
                dados = ITENS[slot[0]]
                botao["text"] = f"{dados['nome']}\nx{slot[1]}"
                botao["frameColor"] = tuple(c * 0.55 for c in dados["cor"][:3]) + (0.95,)
            else:
                botao["text"] = ""
                botao["frameColor"] = (0.2, 0.2, 0.2, 0.85)

    def abrir_leitura(self, texto):
        self.lendo = True
        self.painel_leitura["text"] = texto
        self.painel_leitura.show()

    def fechar_leitura(self):
        self.lendo = False
        self.painel_leitura.hide()

    def alternar_diario(self):
        if self.lendo:
            self.fechar_leitura()
            return
        if self.morto:
            return
        if not self.diario:
            texto = "DIARIO\n\nVoce ainda nao encontrou nenhuma pista."
        else:
            partes = [f"[{NOTAS[i]['titulo']}]\n{NOTAS[i]['texto']}" for i in self.diario]
            texto = "DIARIO\n\n" + "\n\n".join(partes) + "\n\n[J] fechar"
        self.abrir_leitura(texto)

    def mostrar_mensagem(self, texto, duracao=3.0):
        self.texto_mensagem.setText(texto)
        self.tempo_mensagem = duracao

    @staticmethod
    def definir_texto(widget, texto):
        if widget.getText() != texto:
            widget.setText(texto)

    def atualizar_interface(self, dt):
        self.barra_vida["value"] = self.vida
        self.barra_fome["value"] = self.fome
        self.barra_sede["value"] = self.sede
        self.barra_pilha["value"] = self.bateria
        self.definir_texto(self.texto_tempo, f"Dia {self.ciclo.dia} - {self.ciclo.hora_texto}")

        for i, quadro in enumerate(self.hotbar):
            slot = self.mochila[i]
            texto = f"{i + 1}: {ITENS[slot[0]]['nome']} x{slot[1]}" if slot else f"{i + 1}: -"
            if quadro["text"] != texto:
                quadro["text"] = texto

        if self.tempo_mensagem > 0:
            self.tempo_mensagem -= dt
            if self.tempo_mensagem <= 0:
                self.texto_mensagem.setText("")
        if self.tempo_save_msg > 0:
            self.tempo_save_msg -= dt
            if self.tempo_save_msg <= 0:
                self.texto_save.setText("")

        dica = ""
        if not self.morto and not self.lendo and not self.inventario_aberto:
            c = self.item_proximo()
            if c:
                if c["tipo"] == "nota":
                    dica = f"[E] Ler: {NOTAS[c['id']]['titulo']}"
                else:
                    extra = f" x{c['qtd']}" if c["qtd"] > 1 else ""
                    dica = f"[E] Pegar: {ITENS[c['id']]['nome']}{extra}"
        self.definir_texto(self.texto_dica, dica)

        self.flash_dano = max(0.0, self.flash_dano - dt)
        self.overlay_dano["frameColor"] = (0.7, 0, 0, min(0.5, self.flash_dano))

    # ------------------------------------------------------------------
    # Controles e loop principal
    # ------------------------------------------------------------------
    def configurar_controles(self):
        self.teclas = {"frente": False, "tras": False, "esquerda": False,
                       "direita": False, "correr": False}
        for tecla, acao in (("w", "frente"), ("s", "tras"), ("a", "esquerda"),
                            ("d", "direita"), ("shift", "correr")):
            self.accept(tecla, self.definir_tecla, [acao, True])
            self.accept(tecla + "-up", self.definir_tecla, [acao, False])

        self.accept("space", self.pular)
        self.accept("mouse1", self.atacar)
        self.accept("e", self.coletar)
        self.accept("f", self.alternar_lanterna)
        self.accept("j", self.alternar_diario)
        self.accept("tab", self.alternar_mochila)
        self.accept("r", self.reiniciar)
        self.accept("escape", self.alternar_mouse)
        self.accept("f5", self.salvar)
        self.accept("f9", self.carregar_manual)
        self.accept("f3", self.alternar_fps)
        for i in range(4):
            self.accept(str(i + 1), self.usar_slot, [i])

    def definir_tecla(self, tecla, pressionada):
        self.teclas[tecla] = pressionada

    def carregar_manual(self):
        if os.path.exists(ARQUIVO_SAVE):
            self.carregar(False)
        else:
            self.mostrar_mensagem("Nenhum salvamento encontrado.", 2.5)

    def alternar_fps(self):
        self.medidor_fps = not self.medidor_fps
        self.setFrameRateMeter(self.medidor_fps)

    def atualizar(self, task):
        dt = min(ClockObject.getGlobalClock().getDt(), 1 / 30)

        self.ler_mouse()
        self.ciclo.atualizar(dt)
        if self.ciclo.dia != self.ultimo_dia:
            self.ultimo_dia = self.ciclo.dia
            self.novo_dia()
        self.recarga_ataque = max(0.0, self.recarga_ataque - dt)

        if not self.morto:
            self.mover_jogador(dt)
            self.atualizar_sobrevivencia(dt)
            self.tempo_autosave -= dt
            if self.tempo_autosave <= 0:
                self.tempo_autosave = INTERVALO_AUTOSAVE
                self.salvar(auto=True)

        self.mundo.doPhysics(dt, 5, 1 / 90)

        pos = self.jogador.getPos()
        if pos.z < -20:                               # seguranca: caiu do mapa
            self.jogador.setPos(*POSICAO_INICIAL)

        self.ciclo.seguir(pos)
        self.atualizar_janelas(dt)
        self.gerenciar_monstros(dt, pos)
        for c in self.coletaveis:                     # itens girando
            c["no"].setH(c["no"].getH() + 90 * dt)

        self.atualizar_camera(pos, dt)
        self.atualizar_interface(dt)
        return Task.cont


if __name__ == "__main__":
    SurvivalGame().run()