/**
 * Estado compartido entre la página guiada y el panel de detalle.
 *
 * Con signals, sin NgModules ni store externo: el flujo tiene cinco pasos y una
 * ruta secundaria, no hace falta más.
 *
 * Regla que se sostiene desde aquí: **la capacidad siempre viene del backend.**
 * Ningún componente decide por su cuenta si la estrategia está personalizada, ni
 * escribe el umbral de horas en ninguna parte.
 *
 * Y otra: **el historial vive aquí, no en el servidor.** Los tramos procesados
 * se guardan en esta señal y viajan en cada petición que los necesita; al
 * salir, con borrar la señal no queda nada en ningún sitio.
 */
import { Injectable, computed, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import type {
  Capacidad,
  Estrategia,
  HistorialProcesado,
  ResumenHistorial,
  Salud,
} from './api.service';
import { duracion } from './formato';

/** El texto del disclaimer, derivado del motivo que da el backend. */
export interface Disclaimer {
  tono: 'aviso' | 'error' | 'ok';
  titulo: string;
  cuerpo: string;
}

/**
 * Por debajo de esto, «lo que te falta» se redondea a cero y decir «te faltan
 * 0 min» queda absurdo. Pasa cuando las horas caen justo en el borde de una
 * franja (a 124.7 h, la siguiente empieza en 124.72).
 */
const HORAS_DESPRECIABLES = 0.1;

/**
 * Los valores con los que arranca el formulario del objetivo.
 *
 * Estan aqui, y no escritos dos veces, porque `reiniciar()` tiene que poder
 * devolverlos a este mismo punto: salir y volver a entrar deja la aplicacion
 * como recien abierta, no a medias.
 */
const TIEMPO_OBJETIVO_POR_DEFECTO = 4;
const TEMPERATURA_POR_DEFECTO = 18;

/**
 * Mientras no hay ruta cargada, la capacidad se consulta para una maratón: es
 * el régimen objetivo del producto. Al calcular, manda la distancia del `.GPX`.
 */
export const KM_MARATON = 42.2;

/** El historial de esta persona: los tramos procesados y lo que dicen de ella. */
export interface HistorialLocal {
  procesado: HistorialProcesado;
  resumen: ResumenHistorial;
}

/** El umbral a partir del cual el sistema personaliza, tal como lo da la API. */
export interface UmbralPersonalizacion {
  horas: number;
  kmObjetivo: number;
}

@Injectable({ providedIn: 'root' })
export class EstadoService {
  private api = inject(ApiService);

  // --- Estado ---------------------------------------------------------------

  readonly salud = signal<Salud | null>(null);
  readonly historial = signal<HistorialLocal | null>(null);
  readonly gpx = signal<File | null>(null);
  readonly kmRuta = signal<number | null>(null);
  readonly capacidad = signal<Capacidad | null>(null);
  readonly estrategia = signal<Estrategia | null>(null);

  /**
   * La capacidad vigente. Llega por dos vias -la consulta directa a
   * `/capacidad` y la que viene dentro de la estrategia- y manda la primera,
   * que es la mas reciente. Vive aqui porque esta misma cadena estaba
   * repetida en cinco sitios.
   */
  readonly capacidadEfectiva = computed(
    () => this.capacidad() ?? this.estrategia()?.capacidad ?? null,
  );

  readonly tiempoObjetivoH = signal<number>(TIEMPO_OBJETIVO_POR_DEFECTO);
  readonly temperaturaC = signal<number>(TEMPERATURA_POR_DEFECTO);

  readonly sesionGarminId = signal<string | null>(null);
  readonly garminAutenticada = signal(false);

  readonly cargando = signal<string | null>(null);
  readonly error = signal<string | null>(null);

  /**
   * Una entrada que todavía está llegando: los `.FIT` subiéndose, o el
   * historial bajando de Garmin.
   *
   * Vive aquí y no en el componente que la lanza porque la descarga de Garmin
   * ocurre dentro del diálogo del paso 1 y tarda de diez a veinte minutos:
   * durante ese rato el botón de calcular está cinco pantallas más abajo y no
   * se enteraba de nada. El texto es el que enseña el botón mientras espera.
   */
  readonly entradaEnCurso = signal<string | null>(null);

  /** Cuando «lo que falta» se redondea a cero, no se dice una cifra. */
  readonly faltaPocoParaLaSiguiente = computed(() => {
    const cap = this.capacidadEfectiva();
    const siguiente = cap?.siguiente_franja;
    return siguiente !== null && siguiente !== undefined
      ? siguiente.horas_faltantes < HORAS_DESPRECIABLES
      : false;
  });

  /** Cuántas horas hacen falta para que el sistema personalice. Sale de la API. */
  readonly umbral = signal<UmbralPersonalizacion | null>(null);

  // --- Derivados ------------------------------------------------------------

  readonly hayHistorial = computed(() => this.historial() !== null);
  readonly hayRuta = computed(() => this.gpx() !== null);
  readonly hayEstrategia = computed(() => this.estrategia() !== null);

  /**
   * Si este despliegue tiene la conexión con Garmin.
   *
   * Necesita una sesión viva en el servidor, y el despliegue sin estado (el
   * publicado) no la tiene: allí se esconde y se explica cómo exportar los
   * `.FIT`. Lo dice `GET /health`, no una bandera escrita aquí.
   */
  readonly garminDisponible = computed(() => this.salud()?.garmin_habilitado === true);

  /** Si el servidor tiene cargada la regla de capacidad; sin ella no se calcula nada. */
  readonly reglasCargadas = computed(() => this.salud()?.reglas.cargadas !== false);

  /**
   * Si no hay nada cargado, salir no destruye nada.
   *
   * Lo usa la guarda de salida para no preguntar: un aviso que dice que se van
   * a borrar datos inexistentes es, literalmente, falso.
   */
  readonly hayAlgoQuePerder = computed(
    () =>
      this.hayHistorial() || this.hayRuta() || this.hayEstrategia() || this.garminAutenticada(),
  );

  /**
   * Calcular con una entrada a medio llegar daría una estrategia construida
   * sobre datos incompletos, así que el botón se apaga mientras haya alguna en
   * curso, venga de donde venga.
   */
  readonly puedeCalcular = computed(
    () =>
      this.hayRuta() &&
      this.hayHistorial() &&
      this.tiempoObjetivoH() > 0 &&
      this.cargando() === null &&
      this.entradaEnCurso() === null,
  );

  /** Lo que dice el botón de calcular. Si está bloqueado, dice por qué. */
  readonly textoCalcular = computed(
    () => this.cargando() ?? this.entradaEnCurso() ?? 'Calcular mi estrategia',
  );

  /**
   * El aviso de la estrategia: un título y una frase, a partir del `motivo`
   * que devuelve el backend.
   *
   * Los tres casos son distintos y no se pueden colapsar en "te faltan horas":
   * si la carrera es corta, el límite es la distancia y decir lo otro sería
   * falso. Ver `regimen_fiable`. El detalle largo vive en «por qué esta
   * estrategia»; aquí va lo que cabe en un vistazo.
   */
  readonly disclaimer = computed<Disclaimer | null>(() => {
    const cap = this.capacidadEfectiva();
    if (!cap) return null;

    if (cap.personalizada) {
      if (!cap.regimen_fiable) {
        return {
          tono: 'aviso',
          titulo: 'Personalizada, pero con poca evidencia detrás',
          cuerpo:
            'A esta distancia ningún modelo supera con claridad al ritmo constante: ' +
            'tómala como orientación.',
        };
      }
      return {
        tono: 'ok',
        titulo: 'Estrategia personalizada',
        cuerpo:
          `Con ${this.horas(cap.horas)} de historial se ajusta a tu forma de correr. ` +
          `Reduce alrededor de un ${Math.round(cap.habilidad_esperada * 100)}% el error ` +
          `frente a salir a ritmo fijo.`,
      };
    }

    switch (cap.motivo) {
      case 'distancia_sin_evidencia':
        return {
          tono: 'aviso',
          titulo: 'Ritmo constante: es la distancia, no tu historial',
          cuerpo: `En ${cap.km_objetivo.toFixed(1)} km apenas hay fatiga que anticipar: más horas no lo cambian.`,
        };

      case 'historial_insuficiente':
      case 'sin_evidencia_en_esta_franja': {
        const siguiente = cap.siguiente_franja;
        let cuerpo = `Con ${this.horas(cap.horas)} todavía no hay con qué ajustarla a ti.`;
        if (siguiente && siguiente.horas_faltantes >= HORAS_DESPRECIABLES) {
          cuerpo = `Con ${this.horas(cap.horas)} todavía no hay con qué ajustarla a ti: te faltan ${this.horas(siguiente.horas_faltantes)}.`;
        } else if (siguiente) {
          cuerpo = 'Estás justo en el borde: con un poco más de historial ya entrarías.';
        }
        return {
          tono: 'aviso',
          titulo: 'Ritmo constante: todavía no hay evidencia para personalizar',
          cuerpo,
        };
      }

      default:
        return {
          tono: 'aviso',
          titulo: 'Ritmo constante',
          cuerpo: 'Todavía no hay evidencia suficiente para personalizar.',
        };
    }
  });

  /**
   * Cuánto se pudo ajustar la estrategia a esta persona, en palabras.
   *
   * No se inventa ningún umbral aquí: sale de `nivel_capacidad`, el entero que
   * el backend ya calcula (`reglas.NIVEL_CAPACIDAD` = cuánta evidencia pide cada
   * familia de modelo). Traducirlo es presentación; decidirlo, no.
   */
  readonly nivelPersonalizacion = computed<string | null>(() => {
    const cap = this.capacidadEfectiva();
    if (!cap) return null;
    if (!cap.personalizada) return 'sin personalizar';

    return { 1: 'media', 2: 'alta', 3: 'máxima' }[cap.nivel_capacidad] ?? 'media';
  });

  /** Aviso aparte: la distancia cae fuera de lo que se validó (16-42 km). */
  readonly avisoExtrapolacion = computed(() => {
    const cap = this.capacidadEfectiva();
    if (!cap?.distancia_extrapolada) return null;

    const [min, max] = cap.validado_en_km;
    return (
      `Solo se validó con carreras de ${min} a ${max} km: para ${cap.km_objetivo.toFixed(1)} km ` +
      `es una extrapolación.`
    );
  });

  // --- Acciones -------------------------------------------------------------

  horas(valor: number): string {
    if (valor < 1) return `${Math.round(valor * 60)} min`;
    return `${valor.toFixed(1)} h`;
  }

  /** El tiempo objetivo, en horas y minutos: «4 h 00 min». */
  tiempo(horas: number): string {
    return duracion(horas);
  }

  /**
   * Guarda un historial recién procesado y le pregunta a la API qué dice de él.
   *
   * Vale igual para los `.FIT` subidos y para lo que baja de Garmin. La
   * capacidad se consulta con la distancia de la ruta si ya se conoce, y si no,
   * con la de una maratón.
   */
  async aplicarHistorial(procesado: HistorialProcesado): Promise<void> {
    const resumen = await this.api.resumenHistorial(
      procesado.tramos,
      this.kmRuta() ?? KM_MARATON,
    );
    this.historial.set({ procesado, resumen });
    this.capacidad.set(resumen.capacidad ?? null);
    this.invalidarEstrategia();
  }

  /**
   * Pregunta a la API a partir de cuántas horas empieza a personalizar.
   *
   * Consultando con `horas = 0`, `siguiente_franja` es la primera franja medida.
   * El número **no** se escribe en el frontend: depende de la distancia (10 h en
   * maratón, 1.8 h en carrera corta), así que dejarlo fijo sería falso.
   */
  async cargarUmbral(kmObjetivo: number): Promise<void> {
    if (this.umbral()?.kmObjetivo === kmObjetivo) return;

    try {
      const capacidad = await this.api.capacidad(0, kmObjetivo);
      const horas = capacidad.siguiente_franja?.horas_faltantes;
      if (horas !== undefined && horas !== null) this.umbral.set({ horas, kmObjetivo });
    } catch {
      // Es un dato de ayuda: si no se puede traer, se calla en vez de inventarlo.
      this.umbral.set(null);
    }
  }

  limpiarError(): void {
    this.error.set(null);
  }

  /** Al cambiar historial o ruta, la estrategia anterior deja de valer. */
  invalidarEstrategia(): void {
    this.estrategia.set(null);
  }

  /**
   * Salir y no dejar rastro.
   *
   * El historial y la estrategia viven aquí, así que con limpiar las señales
   * desaparecen. Lo único que puede quedar en el servidor es la sesión de
   * Garmin (en local), y esa se cierra antes de limpiar: después ya no
   * quedaría el identificador que hay que mandar.
   */
  async olvidar(): Promise<void> {
    const sesionGarmin = this.sesionGarminId();
    if (sesionGarmin) await this.api.olvidar({ sesion_garmin_id: sesionGarmin });
    this.reiniciar();
  }

  /**
   * Deja la aplicacion como recien abierta.
   *
   * Tiene que estar todo: una señal que se olvide aqui es un dato de la persona
   * anterior que sobrevive a su salida.
   */
  reiniciar(): void {
    this.historial.set(null);
    this.gpx.set(null);
    this.kmRuta.set(null);
    this.capacidad.set(null);
    this.estrategia.set(null);
    this.error.set(null);
    this.cargando.set(null);
    this.entradaEnCurso.set(null);
    this.sesionGarminId.set(null);
    this.garminAutenticada.set(false);
    this.umbral.set(null);
    this.tiempoObjetivoH.set(TIEMPO_OBJETIVO_POR_DEFECTO);
    this.temperaturaC.set(TEMPERATURA_POR_DEFECTO);
  }
}
