/**
 * Cómo se le enseñan los números a una persona.
 *
 * El backend habla en unidades de cálculo —min/km decimales, horas decimales,
 * fechas ISO, claves de control de calidad— y aquí se traducen a lo que un
 * corredor lee de un vistazo: `5:04 /km`, `4 h 12 min`, `28 ago – 5 nov 2024`.
 * Un solo sitio para que la tabla, la gráfica y los pasos del reloj digan lo
 * mismo con el mismo formato.
 */

/** Ritmo en min/km decimales a `m:ss`. 5.06 → «5:04». */
export function ritmo(minKm: number): string {
  let minutos = Math.floor(minKm);
  let segundos = Math.round((minKm - minutos) * 60);
  // 5.999 redondea a 6:00, no a 5:60.
  if (segundos === 60) {
    minutos += 1;
    segundos = 0;
  }
  return `${minutos}:${String(segundos).padStart(2, '0')}`;
}

/** Un rango de ritmos, del más rápido al más lento: «4:51–5:06». */
export function rangoRitmo(a: number, b: number): string {
  const [rapido, lento] = a <= b ? [a, b] : [b, a];
  const izquierda = ritmo(rapido);
  const derecha = ritmo(lento);
  return izquierda === derecha ? izquierda : `${izquierda}–${derecha}`;
}

/** Horas decimales a «4 h 05 min», o «45 min» si no llega a una hora. */
export function duracion(horas: number): string {
  let h = Math.floor(horas);
  let m = Math.round((horas - h) * 60);
  if (m === 60) {
    h += 1;
    m = 0;
  }
  if (h === 0) return `${m} min`;
  return `${h} h ${String(m).padStart(2, '0')} min`;
}

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

/**
 * `AAAA-MM-DD` a sus partes, sin pasar por `Date`.
 *
 * `new Date('2024-08-28')` se interpreta como medianoche UTC, y en México eso
 * es el día anterior: la fecha se mostraría un día antes de la real.
 */
function partes(iso: string): { dia: number; mes: number; anio: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return { anio: Number(m[1]), mes: Number(m[2]), dia: Number(m[3]) };
}

/** «2024-08-28» → «28 ago 2024». Si no es una fecha, se devuelve tal cual. */
export function fecha(iso: string): string {
  const p = partes(iso);
  return p ? `${p.dia} ${MESES[p.mes - 1]} ${p.anio}` : iso;
}

/**
 * Un periodo legible: «28 ago – 5 nov 2024», o con los dos años si cambian.
 * Si es un solo día, solo ese día.
 */
export function periodo(desde: string, hasta: string): string {
  const a = partes(desde);
  const b = partes(hasta);
  if (!a || !b) return `${desde} – ${hasta}`;
  if (desde === hasta) return fecha(desde);
  if (a.anio === b.anio) {
    return `${a.dia} ${MESES[a.mes - 1]} – ${b.dia} ${MESES[b.mes - 1]} ${b.anio}`;
  }
  return `${fecha(desde)} – ${fecha(hasta)}`;
}

/** Semanas completas entre dos fechas ISO, contando las dos puntas. */
export function semanas(desde: string, hasta: string): number {
  const a = partes(desde);
  const b = partes(hasta);
  if (!a || !b) return 0;
  const dias =
    (Date.UTC(b.anio, b.mes - 1, b.dia) - Date.UTC(a.anio, a.mes - 1, a.dia)) / 86_400_000;
  return Math.max(1, Math.round((dias + 1) / 7));
}

/**
 * Los motivos del control de calidad, en palabras.
 *
 * El backend los nombra por el campo que falta (`sin enhanced_altitude`), que es
 * exacto pero no le dice nada a quien corre. Lo que no está en la lista se
 * traduce campo a campo, para que un motivo nuevo no salga en crudo.
 */
const MOTIVOS: Record<string, string> = {
  ok: 'válidas',
  'no es carrera continua': 'caminatas o con pausas largas',
  'sesión demasiado corta': 'demasiado cortas',
  'archivo ilegible': 'no se pudieron leer',
  'archivo vacío': 'vacías',
  'sin registros': 'sin registros',
  'sin splits válidos': 'sin tramos válidos',
};

const CAMPOS: Record<string, string> = {
  enhanced_altitude: 'altímetro',
  heart_rate: 'pulso',
  cadence: 'cadencia',
  distance: 'distancia',
  enhanced_speed: 'velocidad',
};

export function motivo(clave: string): string {
  if (clave in MOTIVOS) return MOTIVOS[clave];
  if (clave.startsWith('sin ')) {
    const campos = clave
      .slice(4)
      .split(',')
      .map((campo) => CAMPOS[campo.trim()] ?? campo.trim());
    return `sin ${campos.join(', ')}`;
  }
  return clave;
}
