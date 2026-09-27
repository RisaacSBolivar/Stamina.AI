/**
 * La página guiada: historial → ruta → objetivo → estrategia → reloj.
 *
 * Un solo recorrido, con las secciones habilitándose conforme hay datos. Es lo
 * más fiel al diseño original (una página de Streamlit) y lo que mejor encaja
 * en los 5 minutos de demo que pide la rúbrica.
 *
 * Lo visual va primero: la estrategia se cuenta con una frase, tres cifras, la
 * gráfica y la carrera por capítulos; el detalle queda plegado o en un ⓘ. El
 * aviso sale de `EstadoService.disclaimer`, que lo deriva del `motivo` que
 * devuelve el backend. Aquí no hay ningún umbral escrito.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Injector,
  OnInit,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { CarreraCapitulos } from '../../componentes/carrera-capitulos';
import { DialogoGarmin } from '../../componentes/dialogo-garmin';
import { GraficaEstrategia } from '../../componentes/grafica-estrategia';
import { MedidorEvidencia } from '../../componentes/medidor-evidencia';
import { ResumenCarrera } from '../../componentes/resumen-carrera';
import { ZonaSoltar } from '../../componentes/zona-soltar';
import {
  ApiService,
  ErrorApi,
  type ClaveObjetivo,
  type OpcionObjetivo,
} from '../../core/api.service';
import { ConfirmacionService } from '../../core/confirmacion.service';
import { EstadoService, KM_MARATON } from '../../core/estado.service';
import { duracion, motivo, periodo, rangoRitmo, ritmo, semanas } from '../../core/formato';

/** Lo que tarda en contestar un servidor despierto, con holgura. */
const MS_ANTES_DE_AVISAR_ARRANQUE = 3000;

@Component({
  selector: 'app-estrategia-page',
  imports: [
    FormsModule,
    RouterLink,
    ZonaSoltar,
    GraficaEstrategia,
    DialogoGarmin,
    MedidorEvidencia,
    ResumenCarrera,
    CarreraCapitulos,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './estrategia.page.html',
})
export class EstrategiaPage implements OnInit {
  private api = inject(ApiService);
  private confirmacion = inject(ConfirmacionService);
  private inyector = inject(Injector);
  protected estado = inject(EstadoService);

  protected readonly opciones = signal<OpcionObjetivo[]>([]);
  protected readonly objetivo = signal<ClaveObjetivo>('terminar sin fatiga');
  protected readonly sugerencia = signal<string | null>(null);
  protected readonly mostrarGarmin = signal(false);
  protected readonly resultadoSubida = signal<string | null>(null);
  /** El servidor tarda en contestar la primera vez: probablemente está arrancando. */
  protected readonly despertando = signal(false);

  // Los formateadores, a mano de la plantilla.
  protected readonly ritmo = ritmo;
  protected readonly rangoRitmo = rangoRitmo;
  protected readonly duracion = duracion;

  protected readonly puedeSugerir = computed(
    () => this.estado.hayHistorial() && this.estado.kmRuta() !== null,
  );

  /** El periodo del historial, legible: «28 ago – 5 nov 2024 · 10 semanas». */
  protected readonly periodoHistorial = computed(() => {
    const resumen = this.estado.historial()?.resumen;
    if (!resumen) return null;
    const n = semanas(resumen.desde, resumen.hasta);
    return `${periodo(resumen.desde, resumen.hasta)} · ${n} ${n === 1 ? 'semana' : 'semanas'}`;
  });

  /** El control de calidad en palabras: primero las válidas, luego los descartes. */
  protected readonly controlCalidad = computed(() => {
    const cc = this.estado.historial()?.procesado.control_calidad ?? {};
    const validas = cc['ok'] ?? 0;
    const descartes = Object.entries(cc)
      .filter(([clave]) => clave !== 'ok')
      .map(([clave, n]) => ({ n, etiqueta: motivo(clave) }));
    return {
      validas,
      descartadas: descartes.reduce((suma, d) => suma + d.n, 0),
      descartes,
    };
  });

  async ngOnInit(): Promise<void> {
    // El servidor gratuito se duerme tras un rato sin uso y tarda cerca de un
    // minuto en despertar. Si la primera respuesta no llega enseguida, se dice
    // por qué, en vez de dejar la página callada.
    const aviso = setTimeout(() => this.despertando.set(true), MS_ANTES_DE_AVISAR_ARRANQUE);
    try {
      const [salud, opciones] = await Promise.all([
        this.api.salud(),
        this.api.opcionesObjetivo(),
      ]);
      this.estado.salud.set(salud);
      this.opciones.set(opciones);

      const porDefecto = opciones.find((o) => o.por_defecto);
      if (porDefecto) this.objetivo.set(porDefecto.clave);

      // A partir de cuántas horas personaliza el sistema. Se pregunta a la API
      // porque depende de la distancia y no puede estar escrito aquí.
      await this.estado.cargarUmbral(this.estado.kmRuta() ?? KM_MARATON);
    } catch (error) {
      this.estado.error.set(
        error instanceof ErrorApi ? error.message : 'No se pudo contactar con el servidor.',
      );
    } finally {
      clearTimeout(aviso);
      this.despertando.set(false);
    }
  }

  // --- Paso 1: historial ----------------------------------------------------

  protected async subirHistorial(archivos: File[]): Promise<void> {
    await this.conCarga(
      'Procesando tu historial…',
      async () => {
        const procesado = await this.api.procesarHistorial(archivos, (tanda, total) => {
          // Con una sola tanda no hace falta decir nada más.
          if (total > 1) this.avisarEspera(`Procesando tu historial… (${tanda} de ${total})`);
        });
        await this.estado.aplicarHistorial(procesado);
      },
      { esEntrada: true },
    );
  }

  /**
   * Abre el panel de Garmin, que vive en el paso 1, y lleva la vista hasta él.
   *
   * Sin el desplazamiento el botón del paso 5 parecía no hacer nada: el panel se
   * abre cinco pantallas más arriba.
   */
  protected abrirGarmin(): void {
    this.mostrarGarmin.set(true);
    // Dos detalles que costaron una prueba cada uno:
    // - `afterNextRender` y no `setTimeout`: el panel se crea dentro de un
    //   `@if`, así que justo después de mover la señal todavía no está en el
    //   DOM y el desplazamiento se perdía en silencio.
    // - Sin `behavior: 'smooth'`: donde la animación está desactivada, el
    //   desplazamiento suave no se ejecuta y no pasa nada. Además, para un
    //   salto de cinco pantallas el corte seco se sigue mejor que la animación.
    afterNextRender(
      () => document.getElementById('panel-garmin')?.scrollIntoView({ block: 'center' }),
      { injector: this.inyector },
    );
  }

  protected omitirHistorial(): void {
    this.estado.historial.set(null);
    this.estado.capacidad.set(null);
    this.estado.invalidarEstrategia();
  }

  // --- Paso 2: ruta ---------------------------------------------------------

  protected cargarRuta(archivos: File[]): void {
    const gpx = archivos[0];
    if (!gpx.name.toLowerCase().endsWith('.gpx')) {
      this.estado.error.set(`«${gpx.name}» no es un .GPX. La ruta se carga en ese formato.`);
      return;
    }
    this.estado.error.set(null);
    this.estado.gpx.set(gpx);
    this.estado.invalidarEstrategia();
    // La distancia real sale del .GPX al calcular; hasta entonces no se sabe,
    // así que la consulta de capacidad se hace con la estrategia.
    this.estado.kmRuta.set(null);
  }

  // --- Paso 3: objetivo -----------------------------------------------------

  protected async pedirSugerencia(): Promise<void> {
    const historial = this.estado.historial();
    const km = this.estado.kmRuta();
    if (!historial || km === null) return;

    await this.conCarga('Calculando una sugerencia…', async () => {
      const s = await this.api.sugerencia(historial.procesado.tramos, km, this.objetivo());
      if (s.tiempo_objetivo_h) {
        this.estado.tiempoObjetivoH.set(Number(s.tiempo_objetivo_h.toFixed(2)));
        this.sugerencia.set(
          `Propuesta a partir de tus carreras: ${ritmo(s.ritmo_medio_min_km ?? 0)} /km de media.`,
        );
      } else {
        // Sin una sesión larga de referencia el backend no sugiere nada y
        // explica por qué; entonces el tiempo lo teclea el usuario.
        this.sugerencia.set(s.motivo ?? null);
      }
    });
  }

  // --- Paso 4: estrategia ---------------------------------------------------

  protected async calcular(): Promise<void> {
    const gpx = this.estado.gpx();
    const historial = this.estado.historial();
    if (!gpx || !historial) return;

    await this.conCarga('Calculando tu estrategia…', async () => {
      const estrategia = await this.api.estrategia(
        gpx,
        historial.procesado.tramos,
        this.estado.tiempoObjetivoH(),
        this.estado.temperaturaC(),
      );
      this.estado.estrategia.set(estrategia);
      this.estado.capacidad.set(estrategia.capacidad);
      this.estado.kmRuta.set(estrategia.ruta.km_totales);
      this.resultadoSubida.set(null);
    });
  }

  // --- Paso 5: al reloj -----------------------------------------------------

  /** El `.FIT` ya vino con la estrategia: se guarda sin volver a preguntar. */
  protected descargarFit(): void {
    const fit = this.estado.estrategia()?.fit;
    if (!fit) return;

    const bytes = Uint8Array.from(atob(fit.contenido_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.ant.fit' }));
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = fit.nombre_archivo;
    enlace.click();
    URL.revokeObjectURL(url);
  }

  /**
   * Subida a Garmin: botón separado, acción explícita y confirmación aparte.
   * Nunca se dispara como efecto de calcular ni de descargar.
   */
  protected async subirAGarmin(): Promise<void> {
    const estrategia = this.estado.estrategia();
    const sesion = this.estado.sesionGarminId();
    if (!estrategia || !sesion) return;

    const seguro = await this.confirmacion.pedir({
      titulo: 'Subir el entrenamiento a Garmin',
      mensaje:
        'Se va a crear un entrenamiento nuevo en tu cuenta de Garmin Connect con esta ' +
        'estrategia. No se modifica ni se borra nada de lo que ya tengas.',
      detalle:
        'El archivo está verificado en formato, Garmin acepta la subida y el entrenamiento ' +
        'se ha probado en un reloj físico.',
      textoConfirmar: 'Subir a Garmin',
    });
    if (!seguro) return;

    await this.conCarga('Subiendo a Garmin…', async () => {
      const resultado = await this.api.subirAGarmin(sesion, estrategia.entrenamiento);
      const pasos = estrategia.entrenamiento.pasos.length;
      this.resultadoSubida.set(
        resultado.todos_por_distancia
          ? `Listo: ya está en tu Garmin Connect, con ${pasos} tramos que avanzan solos por distancia.`
          : 'Se subió, pero Garmin no dejó todos los tramos por distancia. Revísalo antes de correr.',
      );
    });
  }

  // --- Utilidades -----------------------------------------------------------

  /** Cambia el texto de espera a mitad de una acción larga. */
  private avisarEspera(mensaje: string): void {
    this.estado.cargando.set(mensaje);
    this.estado.entradaEnCurso.set(mensaje);
  }

  /**
   * Envuelve una acción con el mensaje de espera y el manejo de errores.
   *
   * `esEntrada` marca las que traen datos de entrada —hoy solo la subida del
   * historial—. Esas, además, apagan la zona de soltar archivos mientras duran,
   * igual que hace la descarga de Garmin desde su propio componente.
   */
  private async conCarga(
    mensaje: string,
    accion: () => Promise<void>,
    { esEntrada = false } = {},
  ): Promise<void> {
    this.estado.cargando.set(mensaje);
    if (esEntrada) this.estado.entradaEnCurso.set(mensaje);
    this.estado.error.set(null);
    try {
      await accion();
    } catch (error) {
      this.estado.error.set(
        error instanceof ErrorApi ? error.message : 'Algo salió mal. Inténtalo otra vez.',
      );
    } finally {
      this.estado.cargando.set(null);
      // Solo lo que puso esta llamada: una descarga de Garmin en curso tiene
      // la señal tomada y no le toca a nadie más soltarla.
      if (esEntrada) this.estado.entradaEnCurso.set(null);
    }
  }
}
