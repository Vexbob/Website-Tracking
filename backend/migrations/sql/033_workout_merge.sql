-- Workouts aus BEIDEN JSON-Exportvarianten zusammenfuehren (v1.50.0)
--
-- Auto Health Export liefert dasselbe Workout je nach Exporteinstellung in
-- zwei verschiedenen Auspraegungen. Beide tragen identische Start-/Endzeiten,
-- aber jeweils eine EIGENE, zufaellige "id" -- und jede Variante enthaelt
-- Felder, die der anderen fehlen:
--
--   Variante A: avgHeartRate/maxHeartRate/heartRate{min,avg,max}, die
--               Minutenreihe heartRateData + heartRateRecovery,
--               activeEnergyBurned, elevationUp, lapLength.
--   Variante B: activeEnergy + totalEnergy, elevation{ascent,descent},
--               stepCount/stepCadence/flightsClimbed, swimCadence und
--               totalSwimmingStrokeCount -- dafuer alle Pulswerte auf 0.
--
-- Weil der Ingest bisher die App-id als Identitaet benutzt hat, landete jedes
-- Workout doppelt in der Datenbank: einmal halb ohne Puls, einmal halb ohne
-- Zusatzmetriken. Der Ingest ordnet ab jetzt ueber (Nutzer, Typ, Startzeit)
-- zu; diese Migration raeumt die bereits entstandenen Dubletten auf.

-- ---------- 1. Neue Spalte + Tabelle ----------
-- Der min-Wert des heartRate-Objekts hatte bisher keinen Platz; er gehoert
-- zur selben Kachelgruppe wie Ø und Max und damit in die Kopftabelle.
ALTER TABLE health_workouts ADD COLUMN IF NOT EXISTS min_heart_rate NUMERIC;

-- Die Minutenreihe je Workout (Variante A). "kind" trennt den Verlauf
-- waehrend des Trainings von der Erholungsphase danach, die die App als
-- eigenes Array (heartRateRecovery) mit Zeitstempeln NACH dem Ende liefert.
CREATE TABLE IF NOT EXISTS health_workout_hr_samples (
    id           SERIAL PRIMARY KEY,
    workout_id   INTEGER NOT NULL REFERENCES health_workouts(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL DEFAULT 'workout',
    recorded_at  TIMESTAMPTZ NOT NULL,
    min_bpm      NUMERIC,
    max_bpm      NUMERIC,
    avg_bpm      NUMERIC,
    UNIQUE (workout_id, kind, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_health_workout_hr_workout
    ON health_workout_hr_samples(workout_id, kind, recorded_at);

-- ---------- 2. Zusatzmetrik-Keys vereinheitlichen ----------
-- Der JSON-Ingest hat die App-Schluessel roh gespeichert (swimCadence), der
-- CSV-Ingest kanonische (swim_cadence_spm). Dieselbe Groesse stand dadurch
-- unter zwei Namen in derselben Tabelle -- und im Frontend zweimal, einmal
-- ohne Beschriftung. Kanonisch gewinnt; bereits vorhandene kanonische Zeilen
-- bleiben unangetastet.
UPDATE health_workout_metrics m
   SET metric_key = v.canon
  FROM (VALUES ('swimCadence',    'swim_cadence_spm'),
               ('flightsClimbed', 'flights_climbed'),
               ('stepCount',      'step_count'),
               ('cyclingCadence', 'cadence_spm'),
               ('intensity',      'intensity_kcal_h_kg'),
               ('humidity',       'humidity_pct'),
               ('temperature',    'temperature_c')) AS v(old, canon)
 WHERE m.metric_key = v.old
   AND NOT EXISTS (SELECT 1 FROM health_workout_metrics c
                    WHERE c.workout_id = m.workout_id
                      AND c.metric_key = v.canon);

DELETE FROM health_workout_metrics
 WHERE metric_key IN ('swimCadence', 'flightsClimbed', 'stepCount',
                      'cyclingCadence', 'intensity', 'humidity', 'temperature');

-- ---------- 3. Dubletten zusammenfuehren ----------
-- Gruppe = (Nutzer, Typ, exakte Startzeit). Beide Varianten liefern denselben
-- Zeitstempel auf die Sekunde, ein Zeitfenster ist hier also nicht noetig.
-- Behalten wird die aelteste Zeile (kleinste id), damit bestehende Links und
-- Loeschungen weiter auf dieselbe id zeigen.
--
-- MAX(NULLIF(spalte,0)) waehlt je Spalte den einzigen belegten Wert: die
-- fehlende Variante liefert NULL oder 0. Bei der Distanz greift derselbe
-- Ausdruck den korrekten Meterwert (1825) statt der km-Zahl (1,825).
CREATE TEMP TABLE _wo_dupes ON COMMIT DROP AS
SELECT user_id, workout_type, start_at, MIN(id) AS keep_id
  FROM health_workouts
 GROUP BY user_id, workout_type, start_at
HAVING COUNT(*) > 1;

UPDATE health_workouts w
   SET end_at             = COALESCE(m.end_at, w.end_at),
       duration_min       = COALESCE(m.duration_min, w.duration_min),
       active_energy_kcal = COALESCE(m.active_energy_kcal, w.active_energy_kcal),
       total_energy_kcal  = COALESCE(m.total_energy_kcal, w.total_energy_kcal),
       distance_m         = COALESCE(m.distance_m, w.distance_m),
       avg_heart_rate     = COALESCE(m.avg_heart_rate, w.avg_heart_rate),
       max_heart_rate     = COALESCE(m.max_heart_rate, w.max_heart_rate),
       elevation_m        = COALESCE(m.elevation_m, w.elevation_m)
  FROM (SELECT d.keep_id,
               MAX(x.end_at)                        AS end_at,
               MAX(NULLIF(x.duration_min, 0))       AS duration_min,
               MAX(NULLIF(x.active_energy_kcal, 0)) AS active_energy_kcal,
               MAX(NULLIF(x.total_energy_kcal, 0))  AS total_energy_kcal,
               MAX(NULLIF(x.distance_m, 0))         AS distance_m,
               MAX(NULLIF(x.avg_heart_rate, 0))     AS avg_heart_rate,
               MAX(NULLIF(x.max_heart_rate, 0))     AS max_heart_rate,
               MAX(NULLIF(x.elevation_m, 0))        AS elevation_m
          FROM _wo_dupes d
          JOIN health_workouts x
            ON x.user_id = d.user_id
           AND x.start_at = d.start_at
           AND x.workout_type IS NOT DISTINCT FROM d.workout_type
         GROUP BY d.keep_id) m
 WHERE w.id = m.keep_id;

-- Zusatzmetriken der Dubletten auf die behaltene Zeile umhaengen. Bei
-- Konflikt gewinnt der bereits vorhandene Wert -- er stammt aus derselben
-- Quelle und ist damit gleichwertig.
INSERT INTO health_workout_metrics (workout_id, metric_key, value, unit)
SELECT d.keep_id, m.metric_key, m.value, m.unit
  FROM health_workout_metrics m
  JOIN health_workouts x ON x.id = m.workout_id
  JOIN _wo_dupes d
    ON d.user_id = x.user_id
   AND d.start_at = x.start_at
   AND d.workout_type IS NOT DISTINCT FROM x.workout_type
 WHERE x.id <> d.keep_id
ON CONFLICT (workout_id, metric_key) DO NOTHING;

DELETE FROM health_workouts w
 USING _wo_dupes d
 WHERE w.user_id = d.user_id
   AND w.start_at = d.start_at
   AND w.workout_type IS NOT DISTINCT FROM d.workout_type
   AND w.id <> d.keep_id;

-- ---------- 4. Distanzen aus dem JSON-Import in Meter korrigieren ----------
-- Der JSON-Ingest hat den Rohwert ohne Blick auf das Einheitenfeld in
-- distance_m geschrieben; ein 5,03-km-Spaziergang stand damit als 5 Meter in
-- der Datenbank und die Pace-Kachel blieb leer.
--
-- Zwei Bedingungen muessen zusammenkommen, damit die Zeile sicher als
-- Kilometer zu lesen ist: unter 100 Metern bei mindestens fuenf Minuten Dauer
-- (das gibt es als echte Messung nicht) UND ein Tempo, das als km/h Sinn
-- ergibt. Letzteres schuetzt Workouts, die tatsaechlich nur ein paar Meter
-- mitgeschrieben haben (Krafttraining): 20 Meter in 30 Minuten waeren als
-- Kilometer gelesen 40 km/h und bleiben deshalb unangetastet.
UPDATE health_workouts
   SET distance_m = distance_m * 1000
 WHERE distance_m > 0
   AND distance_m < 100
   AND duration_min >= 5
   AND distance_m / (duration_min / 60) BETWEEN 0.5 AND 30;
