import { opcionesHoras } from './dialogo-garmin';

describe('opcionesHoras', () => {
  it('pone primero lo justo para personalizar, con margen para el control de calidad', () => {
    expect(opcionesHoras(10)).toEqual([13, 50, 135]);
  });

  it('en carrera corta el umbral es menor, y la opción rápida también', () => {
    expect(opcionesHoras(1.8)).toEqual([3, 50, 135]);
  });

  it('sin umbral de la API no se inventa ninguno', () => {
    expect(opcionesHoras(null)).toEqual([50, 135]);
  });

  it('no ofrece opciones amplias por debajo de la justa', () => {
    expect(opcionesHoras(60)).toEqual([78, 135]);
  });
});
