import { duracion, fecha, motivo, periodo, rangoRitmo, ritmo, semanas } from './formato';

describe('formato', () => {
  it('el ritmo en minutos y segundos, no en minutos decimales', () => {
    expect(ritmo(5.06)).toBe('5:04');
    expect(ritmo(4.85)).toBe('4:51');
    expect(ritmo(6)).toBe('6:00');
    // Redondear hacia arriba no puede dar «5:60».
    expect(ritmo(5.999)).toBe('6:00');
  });

  it('un rango de ritmos va del más rápido al más lento', () => {
    expect(rangoRitmo(5.36, 4.85)).toBe('4:51–5:22');
    expect(rangoRitmo(5.83, 5.831)).toBe('5:50');
  });

  it('la duración en horas y minutos', () => {
    expect(duracion(4)).toBe('4 h 00 min');
    expect(duracion(4.21)).toBe('4 h 13 min');
    expect(duracion(0.75)).toBe('45 min');
    expect(duracion(3.9999)).toBe('4 h 00 min');
  });

  it('las fechas, sin el desfase de un día de la zona horaria', () => {
    // new Date('2024-08-28') en México sería el 27: aquí no se pasa por Date.
    expect(fecha('2024-08-28')).toBe('28 ago 2024');
    expect(periodo('2024-08-28', '2024-11-05')).toBe('28 ago – 5 nov 2024');
    expect(periodo('2024-12-20', '2025-01-10')).toBe('20 dic 2024 – 10 ene 2025');
    expect(periodo('2024-03-01', '2024-03-01')).toBe('1 mar 2024');
  });

  it('las semanas del historial', () => {
    expect(semanas('2024-08-28', '2024-11-05')).toBe(10);
    expect(semanas('2024-03-01', '2024-03-01')).toBe(1);
  });

  it('los motivos del control de calidad, en palabras', () => {
    expect(motivo('ok')).toBe('válidas');
    expect(motivo('sin enhanced_altitude')).toBe('sin altímetro');
    expect(motivo('sin heart_rate, cadence')).toBe('sin pulso, cadencia');
    expect(motivo('no es carrera continua')).toBe('caminatas o con pausas largas');
    // Uno que no está en la lista no se inventa: sale tal cual.
    expect(motivo('algo nuevo')).toBe('algo nuevo');
  });
});
