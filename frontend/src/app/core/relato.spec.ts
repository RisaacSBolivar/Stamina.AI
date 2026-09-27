import type { Capacidad, FilaKm, PasoEntrenamiento } from './api.service';
import { enTandas, juntarProcesados, type HistorialProcesado } from './api.service';
import { cifras, medidor, titular } from './relato';

const paso = (km_inicio: number, km_fin: number, zona: string, a: number, b: number) =>
  ({ km_inicio, km_fin, km: km_fin - km_inicio, zona, ritmo_min: a, ritmo_max: b }) as PasoEntrenamiento;

/** Los siete tramos de Atenas con el historial completo. */
const atenas = [
  paso(0, 12, 'Crucero', 4.85, 5.36),
  paso(12, 16, 'Crucero', 5.59, 5.78),
  paso(16, 19, 'Crucero', 5.77, 5.81),
  paso(19, 24, 'Exigencia crítica', 5.83, 5.85),
  paso(24, 28, 'Exigencia crítica', 5.83, 5.85),
  paso(28, 31, 'Exigencia alta', 5.87, 5.95),
  paso(31, 43, 'Exigencia alta', 6.03, 6.19),
];

describe('titular', () => {
  it('cuenta cómo salir y dónde está lo duro', () => {
    expect(titular(atenas, true)).toBe(
      'Sal controlado a 4:51–5:22 /km los primeros 12 km; lo más exigente va del km 19 al 28: ' +
        'guarda fuerzas para ese tramo.',
    );
  });

  it('sin personalizar no promete tramos: ritmo constante', () => {
    expect(titular([paso(0, 43, 'Crucero', 5.68, 5.68)], false)).toBe(
      'Ritmo constante: 5:41 /km de principio a fin.',
    );
  });

  it('un perfil sin exigencia alta lo dice', () => {
    expect(titular([paso(0, 10, 'Crucero', 5, 5.2)], true)).toContain(
      'el perfil no tiene tramos de exigencia alta',
    );
  });
});

describe('cifras', () => {
  it('tiempo, ritmo medio y el km más empinado', () => {
    const tabla = [
      { km: 1, pendiente: 0.4 },
      { km: 22, pendiente: 3.1 },
      { km: 40, pendiente: -2 },
    ] as FilaKm[];
    const c = cifras(tabla, 4, 42.3);

    expect(c.tiempo).toBe('4 h 00 min');
    expect(c.ritmoMedio).toBe('5:40');
    expect(c.kmExigente).toEqual({ km: 22, pendiente: 3.1 });
  });
});

describe('medidor', () => {
  const franjas = [
    { desde_horas: 1.79, nivel: 0 },
    { desde_horas: 4.95, nivel: 0 },
    { desde_horas: 9.99, nivel: 1 },
    { desde_horas: 19.85, nivel: 2 },
    { desde_horas: 39.38, nivel: 1 },
  ];

  it('con 6 h apunta al primer escalón que personaliza, el que da la API', () => {
    const m = medidor({
      horas: 6.14,
      personalizada: false,
      regimen_fiable: true,
      siguiente_franja: { desde_horas: 9.99, horas_faltantes: 3.85 },
      franjas,
    } as unknown as Capacidad)!;

    expect(m.meta).toBe(9.99);
    expect(m.marcas).toEqual([9.99]);
    expect(m.horas / m.escala).toBeLessThan(m.meta / m.escala);
  });

  it('con 12 h marca los dos escalones y apunta al siguiente', () => {
    const m = medidor({
      horas: 12.03,
      personalizada: true,
      regimen_fiable: true,
      siguiente_franja: { desde_horas: 19.85, horas_faltantes: 7.82 },
      franjas,
    } as unknown as Capacidad)!;

    expect(m.meta).toBe(19.85);
    expect(m.marcas).toEqual([9.99, 19.85]);
  });

  it('en una carrera corta no hay barra que llenar', () => {
    expect(medidor({ regimen_fiable: false } as unknown as Capacidad)).toBeNull();
  });
});

describe('subida por tandas', () => {
  const archivo = (kb: number) => new File([new Uint8Array(kb * 1024)], `${kb}.fit`);

  it('parte los archivos sin pasarse del límite y sin cambiar el orden', () => {
    const tandas = enTandas([archivo(300), archivo(300), archivo(300)], 700 * 1024);
    expect(tandas.map((t) => t.map((a) => a.name))).toEqual([['300.fit', '300.fit'], ['300.fit']]);
  });

  it('junta los tramos columna a columna y suma los motivos', () => {
    const parte = (actividad: string, ok: number): HistorialProcesado =>
      ({ tramos: { split: [0, 1], actividad: [actividad, actividad] }, control_calidad: { ok } }) as unknown as HistorialProcesado;

    const junto = juntarProcesados([parte('a', 1), parte('b', 2)]);
    expect(junto.tramos.actividad).toEqual(['a', 'a', 'b', 'b']);
    expect(junto.tramos.split).toEqual([0, 1, 0, 1]);
    expect(junto.control_calidad).toEqual({ ok: 3 });
  });
});
