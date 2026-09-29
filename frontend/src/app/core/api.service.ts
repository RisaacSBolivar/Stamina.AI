/**
 * Cliente de la API.
 *
 * Los tipos NO se escriben a mano: salen de `schema.d.ts`, que genera
 * `make contracts` desde el OpenAPI del backend. Si el backend cambia un campo
 * y aquí no se ajusta, `npx tsc --noEmit` lo caza antes de llegar al navegador.
 *
 * La API no guarda nada de nadie entre peticiones (salvo la sesión y la
 * descarga de Garmin): el historial procesado vive aquí, en el navegador, y
 * viaja entero en cada petición que lo necesita.
 */
import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { lastValueFrom } from 'rxjs';

import { environment } from '../../environments/environment';
import type { components } from './api/schema';

type Esquemas = components['schemas'];

export type Salud = Esquemas['Salud'];
export type Capacidad = Esquemas['Capacidad'];
export type TramosHistorial = Esquemas['TramosHistorial'];
export type HistorialProcesado = Esquemas['HistorialProcesado'];
export type ResumenHistorial = Esquemas['ResumenHistorial'];
export type Estrategia = Esquemas['Estrategia'];
export type FilaKm = Esquemas['FilaKm'];
export type PuntoAltimetria = Esquemas['PuntoAltimetria'];
export type Sugerencia = Esquemas['Sugerencia'];
export type OpcionObjetivo = Esquemas['OpcionObjetivo'];
export type Entrenamiento = Esquemas['Entrenamiento'];
export type PasoEntrenamiento = Esquemas['PasoEntrenamiento'];
export type SesionGarmin = Esquemas['SesionGarmin'];
export type ResultadoSubida = Esquemas['ResultadoSubida'];
export type EstadoDescarga = Esquemas['EstadoDescarga'];
export type RespuestaError = Esquemas['RespuestaError'];
export type ClaveObjetivo = Sugerencia['objetivo'];

/** Cada cuánto se pregunta por el progreso de la descarga de Garmin. */
const MS_ENTRE_CONSULTAS = 2000;

/**
 * Cuántos bytes de `.FIT` van en cada petición.
 *
 * Unas 13 h de historial por tanda. Partir la subida da progreso («2 de 5») y
 * evita una sola petición de minutos; además cabe en el tope de 4.5 MB que
 * tienen algunas plataformas, como las funciones de Vercel. Aquí se juntan los
 * tramos de todas las tandas.
 */
const BYTES_POR_TANDA = 3.5 * 1024 * 1024;

/** Error de dominio del backend: `{ error: { code, message, details } }`. */
export class ErrorApi extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly status = 0,
  ) {
    super(message);
    this.name = 'ErrorApi';
  }
}

/** Parte los archivos en tandas que quepan en una petición, sin cambiar su orden. */
export function enTandas(archivos: File[], limite = BYTES_POR_TANDA): File[][] {
  const tandas: File[][] = [];
  let actual: File[] = [];
  let bytes = 0;
  for (const archivo of archivos) {
    if (actual.length && bytes + archivo.size > limite) {
      tandas.push(actual);
      actual = [];
      bytes = 0;
    }
    actual.push(archivo);
    bytes += archivo.size;
  }
  if (actual.length) tandas.push(actual);
  return tandas;
}

/** Junta el resultado de varias tandas: tramos columna a columna, motivos sumados. */
export function juntarProcesados(partes: HistorialProcesado[]): HistorialProcesado {
  const columnas = Object.keys(partes[0].tramos) as (keyof TramosHistorial)[];
  const tramos = Object.fromEntries(
    columnas.map((c) => [c, partes.flatMap((p) => p.tramos[c] as unknown[])]),
  ) as unknown as TramosHistorial;

  const control_calidad: Record<string, number> = {};
  for (const parte of partes) {
    for (const [motivo, n] of Object.entries(parte.control_calidad)) {
      control_calidad[motivo] = (control_calidad[motivo] ?? 0) + n;
    }
  }
  return { tramos, control_calidad };
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  /** Relativa en desarrollo (proxy) y absoluta en producción (Render): ver `environments/`. */
  readonly base = environment.apiUrl;

  // --- Salud ---------------------------------------------------------------

  salud(): Promise<Salud> {
    return this.get<Salud>('/health');
  }

  // --- Capacidad -----------------------------------------------------------

  /**
   * La consulta de la regla. El umbral NO se escribe en el frontend: depende de
   * las horas y de la distancia objetivo, y sale siempre de aquí.
   */
  capacidad(horas: number, kmObjetivo: number): Promise<Capacidad> {
    const params = new HttpParams()
      .set('horas', String(horas))
      .set('km_objetivo', String(kmObjetivo));
    return this.get<Capacidad>('/capacidad', params);
  }

  // --- Historial -----------------------------------------------------------

  /**
   * Procesa los `.FIT` por tandas y devuelve los tramos juntos.
   *
   * `alAvanzar` recibe la tanda en curso y el total, para que la vista diga
   * por dónde va cuando hay más de una.
   */
  async procesarHistorial(
    archivos: File[],
    alAvanzar?: (tanda: number, total: number) => void,
  ): Promise<HistorialProcesado> {
    const tandas = enTandas(archivos);
    const partes: HistorialProcesado[] = [];
    for (const [indice, tanda] of tandas.entries()) {
      alAvanzar?.(indice + 1, tandas.length);
      const cuerpo = new FormData();
      for (const archivo of tanda) cuerpo.append('archivos', archivo, archivo.name);
      partes.push(await this.post<HistorialProcesado>('/historial/archivos', cuerpo));
    }
    return juntarProcesados(partes);
  }

  resumenHistorial(tramos: TramosHistorial, kmObjetivo?: number): Promise<ResumenHistorial> {
    return this.post<ResumenHistorial>('/historial/resumen', {
      tramos,
      km_objetivo: kmObjetivo ?? null,
    });
  }

  /**
   * Descarga el historial de Garmin, informando del progreso.
   *
   * El backend responde 202 y hace el trabajo aparte: reunir el historial lleva
   * minutos, según las horas pedidas, por la pausa obligatoria contra el límite
   * de peticiones de Garmin, y una petición HTTP abierta ese rato es frágil.
   * Aquí se arranca y se pregunta cada pocos segundos, para que la vista pueda
   * enseñar cuánto lleva. Necesita un servidor con estado, por eso la API vive
   * en un proceso persistente y no en funciones sin servidor.
   *
   * Devuelve `null` si la persona la canceló. Es un caso aparte y no una
   * excepción a propósito: cancelar no es que algo saliera mal, y pintarlo
   * en rojo junto a los errores de Garmin sería mentirle al usuario.
   */
  async descargarDeGarmin(
    sesionGarminId: string,
    objetivoHoras: number,
    alAvanzar?: (estado: EstadoDescarga) => void,
  ): Promise<HistorialProcesado | null> {
    let estado = await this.post<EstadoDescarga>('/historial/garmin', {
      sesion_garmin_id: sesionGarminId,
      objetivo_horas: objetivoHoras,
      // Nunca se manda solo: la vista pide confirmación antes de llamar aquí.
      confirmado: true,
    });
    alAvanzar?.(estado);

    while (estado.estado === 'en_curso') {
      await new Promise((sigue) => setTimeout(sigue, MS_ENTRE_CONSULTAS));
      estado = await this.get<EstadoDescarga>(`/historial/garmin/${estado.tarea_id}`);
      alAvanzar?.(estado);
    }

    if (estado.estado === 'cancelada') return null;

    if (estado.estado === 'fallida' || !estado.resultado) {
      throw new ErrorApi(
        estado.codigo_error ?? 'descarga_fallida',
        estado.error ?? 'La descarga no llegó a terminar.',
      );
    }

    // El historial ya está aquí: que el servidor lo suelte ahora y no cuando
    // caduque la tarea.
    void this.olvidar({ tarea_id: estado.tarea_id });
    return estado.resultado;
  }

  /**
   * Pide que pare una descarga en curso.
   *
   * El backend la marca y responde al instante; el hilo tarda como mucho una
   * actividad en enterarse. Quien consulta el progreso verá el estado nuevo
   * en la siguiente vuelta y saldrá solo.
   */
  cancelarDescarga(tareaId: string): Promise<EstadoDescarga> {
    return this.post<EstadoDescarga>(`/historial/garmin/${tareaId}/cancelar`, {});
  }

  // --- Objetivo ------------------------------------------------------------

  opcionesObjetivo(): Promise<OpcionObjetivo[]> {
    return this.get<OpcionObjetivo[]>('/objetivo/opciones');
  }

  sugerencia(
    tramos: TramosHistorial,
    kmObjetivo: number,
    objetivo: ClaveObjetivo,
  ): Promise<Sugerencia> {
    return this.post<Sugerencia>('/objetivo/sugerencia', {
      tramos,
      km_objetivo: kmObjetivo,
      objetivo,
    });
  }

  // --- Estrategia ----------------------------------------------------------

  /**
   * La estrategia, en una sola petición con todo lo que hace falta.
   *
   * El historial va como archivo JSON y no como campo: uno largo pasa de 1 MB,
   * el tope de un campo de texto en el multipart del backend.
   */
  estrategia(
    gpx: File,
    tramos: TramosHistorial,
    tiempoObjetivoH: number,
    temperaturaC: number,
  ): Promise<Estrategia> {
    const cuerpo = new FormData();
    cuerpo.append('gpx', gpx, gpx.name);
    cuerpo.append(
      'historial',
      new Blob([JSON.stringify(tramos)], { type: 'application/json' }),
      'historial.json',
    );
    cuerpo.append('tiempo_objetivo_h', String(tiempoObjetivoH));
    cuerpo.append('temperatura_c', String(temperaturaC));

    return this.post<Estrategia>('/estrategia', cuerpo);
  }

  // --- Exportación ---------------------------------------------------------

  subirAGarmin(sesionGarminId: string, entrenamiento: Entrenamiento): Promise<ResultadoSubida> {
    return this.post<ResultadoSubida>('/exportar/garmin', {
      sesion_garmin_id: sesionGarminId,
      entrenamiento: {
        nombre: entrenamiento.nombre,
        segundos_estimados: entrenamiento.segundos_estimados,
        pasos: entrenamiento.pasos,
      },
      // La vista ya pidió confirmación explícita antes de llegar aquí.
      confirmado: true,
    });
  }

  // --- Garmin --------------------------------------------------------------

  loginGarmin(correo: string, contrasena: string): Promise<SesionGarmin> {
    return this.post<SesionGarmin>('/garmin/login', { correo, contrasena });
  }

  mfaGarmin(sesionGarminId: string, codigo: string): Promise<SesionGarmin> {
    return this.post<SesionGarmin>('/garmin/mfa', {
      sesion_garmin_id: sesionGarminId,
      codigo,
    });
  }

  cerrarGarmin(sesionGarminId: string): Promise<void> {
    return lastValueFrom(
      this.http.delete<void>(`${this.base}/garmin/sesion/${sesionGarminId}`),
    ).catch(() => undefined);
  }

  // --- Salir ---------------------------------------------------------------

  /**
   * Pide al backend que suelte lo de Garmin: la sesión y una descarga.
   *
   * El historial y la estrategia no hace falta pedirlos: nunca estuvieron allí.
   * No se propaga el fallo: si la llamada no llega, el TTL lo recogerá igual y
   * bloquear la salida por eso sería peor.
   */
  olvidar(ids: { sesion_garmin_id?: string; tarea_id?: string }): Promise<void> {
    return this.post<void>('/sesion/olvidar', ids).catch(() => undefined);
  }

  // --- Internos ------------------------------------------------------------

  private async get<T>(ruta: string, params?: HttpParams): Promise<T> {
    try {
      return await lastValueFrom(this.http.get<T>(`${this.base}${ruta}`, { params }));
    } catch (error) {
      throw this.traducir(error);
    }
  }

  private async post<T>(ruta: string, cuerpo: unknown, params?: HttpParams): Promise<T> {
    try {
      return await lastValueFrom(this.http.post<T>(`${this.base}${ruta}`, cuerpo, { params }));
    } catch (error) {
      throw this.traducir(error);
    }
  }

  /** Desempaqueta el sobre de error del backend para no perder el `code`. */
  private traducir(error: unknown): ErrorApi {
    if (error instanceof HttpErrorResponse) {
      const cuerpo = error.error as Partial<RespuestaError>;
      if (cuerpo?.error?.code) {
        return new ErrorApi(
          cuerpo.error.code,
          cuerpo.error.message,
          (cuerpo.error.details ?? {}) as Record<string, unknown>,
          error.status,
        );
      }
      if (error.status === 0) {
        return new ErrorApi(
          'sin_conexion',
          'No hay conexión con el servidor. Revisa tu conexión y vuelve a intentarlo.',
          {},
          0,
        );
      }
      if (error.status === 413) {
        return new ErrorApi(
          'demasiado_grande',
          'Los archivos pesan demasiado para una sola subida. Prueba con menos a la vez.',
          {},
          413,
        );
      }
      return new ErrorApi('error_http', 'Algo salió mal en el servidor. Inténtalo otra vez.', {}, error.status);
    }
    return new ErrorApi('desconocido', String(error));
  }
}
