/**
 * La estrategia contada en una frase y tres cifras, y el medidor de evidencia.
 *
 * Todo sale de lo que devuelve la API: la tabla por kilómetro, los pasos del
 * reloj y la capacidad. Aquí no se decide nada sobre el corredor —ni umbrales
 * de horas ni si está personalizada—; solo se elige qué contar primero.
 */
import { duracion, rangoRitmo, ritmo } from './formato';
import type { Capacidad, FilaKm, PasoEntrenamiento } from './api.service';
import { SEVERIDAD_ZONA } from './zonas';

// --- El titular --------------------------------------------------------------

/**
 * Una frase que cuente la carrera: cómo salir y dónde está lo duro.
 *
 * Lo duro es el primer tramo seguido de la zona más exigente que aparezca, a
 * partir de «Exigencia alta»: es el sitio donde el ritmo promedio te cobra la
 * factura, y el que conviene tener en la cabeza desde la salida.
 */
export function titular(pasos: PasoEntrenamiento[], personalizada: boolean): string {
  if (!pasos.length) return '';

  if (!personalizada) {
    const medio = pasos.reduce((suma, p) => suma + (p.ritmo_min + p.ritmo_max) / 2, 0) / pasos.length;
    return `Ritmo constante: ${ritmo(medio)} /km de principio a fin.`;
  }

  const primero = pasos[0];
  const salida = `Sal controlado a ${rangoRitmo(primero.ritmo_min, primero.ritmo_max)} /km los primeros ${primero.km} km`;

  const severidad = (p: PasoEntrenamiento) => SEVERIDAD_ZONA[p.zona] ?? 0;
  const maxima = Math.max(...pasos.map(severidad));
  if (maxima < SEVERIDAD_ZONA['Exigencia alta']) {
    return `${salida}: el perfil no tiene tramos de exigencia alta.`;
  }

  const desde = pasos.findIndex((p) => severidad(p) === maxima);
  let hasta = desde;
  while (hasta + 1 < pasos.length && severidad(pasos[hasta + 1]) === maxima) hasta++;

  return (
    `${salida}; lo más exigente va del km ${pasos[desde].km_inicio} al ` +
    `${pasos[hasta].km_fin}: guarda fuerzas para ese tramo.`
  );
}

// --- Las tres cifras ---------------------------------------------------------

export interface Cifras {
  tiempo: string;
  ritmoMedio: string;
  kmExigente: { km: number; pendiente: number } | null;
}

export function cifras(tabla: FilaKm[], tiempoEstimadoH: number, kmTotales: number): Cifras {
  const masEmpinado = tabla.reduce<FilaKm | null>(
    (mejor, fila) => (mejor === null || fila.pendiente > mejor.pendiente ? fila : mejor),
    null,
  );
  return {
    tiempo: duracion(tiempoEstimadoH),
    ritmoMedio: kmTotales > 0 ? ritmo((tiempoEstimadoH * 60) / kmTotales) : '–',
    kmExigente: masEmpinado ? { km: masEmpinado.km, pendiente: masEmpinado.pendiente } : null,
  };
}

// --- El medidor de evidencia -------------------------------------------------

export interface Medidor {
  /** Horas que tiene el corredor. */
  horas: number;
  /** Adonde apunta la barra: el siguiente escalón medido, o sus propias horas. */
  meta: number;
  /** Lo que mide la barra entera, con un margen para que la meta no toque el borde. */
  escala: number;
  /** Las franjas medidas que personalizan, dentro de la escala. */
  marcas: number[];
  personalizada: boolean;
  /** Si ya está justo en el borde del siguiente escalón. */
  enElBorde: boolean;
}

/** Por debajo de esto «te faltan» se redondearía a cero. */
const HORAS_DESPRECIABLES = 0.1;

/**
 * Lo que dibuja el medidor, sacado entero de la capacidad que dio la API.
 *
 * Devuelve `null` cuando acumular horas no cambia nada en este régimen (una
 * carrera corta): ahí una barra que se llena sería una promesa falsa.
 */
export function medidor(cap: Capacidad): Medidor | null {
  if (!cap.regimen_fiable) return null;

  const siguiente = cap.siguiente_franja ?? null;
  const meta = siguiente?.desde_horas ?? cap.horas;
  const escala = Math.max(meta, cap.horas) * 1.15 || 1;
  const marcas = cap.franjas
    .filter((f) => f.nivel > 0 && f.desde_horas <= escala)
    .map((f) => f.desde_horas);

  return {
    horas: cap.horas,
    meta,
    escala,
    marcas,
    personalizada: cap.personalizada,
    enElBorde: siguiente !== null && siguiente.horas_faltantes < HORAS_DESPRECIABLES,
  };
}
