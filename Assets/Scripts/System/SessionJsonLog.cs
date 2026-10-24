using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

/// <summary>One export file per stats session, updated when its summary is viewed.</summary>
public class SessionJsonLog
{
    [Serializable]
    private class SessionData
    {
        public string session_id;
        public string started_at;
        public string ended_at;
        public int shots;
        public int hits;
        public int misses;
        public float accuracy;
        public float avg_reaction_ms;
        public AssistStatePublisher.CalibrationSample[] aim_corrections;
    }

    [Serializable]
    private class ShotData
    {
        public long t_ms;
        public bool hit;
    }

    [Serializable]
    private class TargetShotData : ShotData
    {
        public string target_id;
    }

    [Serializable]
    private class HitShotData : TargetShotData
    {
        public float reaction_ms;
    }

    private SessionData session;
    private double startTime;
    private readonly List<ShotData> shots = new List<ShotData>();

    public void Begin()
    {
        session = new SessionData
        {
            session_id = Guid.NewGuid().ToString("N"),
            started_at = DateTime.UtcNow.ToString("O")
        };
        startTime = Time.realtimeSinceStartupAsDouble;
        shots.Clear();
        if (AssistStatePublisher.Instance != null) AssistStatePublisher.Instance.ResetCalibration();
    }

    public void RegisterShot()
    {
        if (session == null) Begin();
        shots.Add(new ShotData { t_ms = (long)((Time.realtimeSinceStartupAsDouble - startTime) * 1000d) });
    }

    public void RegisterResult(bool hit, string targetId = null, float reactionSeconds = 0f)
    {
        if (shots.Count == 0) return;
        long timestamp = shots[shots.Count - 1].t_ms;
        if (hit)
            shots[shots.Count - 1] = new HitShotData
            {
                t_ms = timestamp, hit = true, target_id = targetId,
                reaction_ms = Mathf.Max(0f, reactionSeconds) * 1000f
            };
        else if (!string.IsNullOrEmpty(targetId))
            shots[shots.Count - 1] = new TargetShotData { t_ms = timestamp, hit = false, target_id = targetId };
    }

    public string Export(ScoreManager score)
    {
        if (session == null || score == null) return null;
        if (AssistStatePublisher.Instance != null) AssistStatePublisher.Instance.FinishCalibration("session_export");
        session.aim_corrections = AssistStatePublisher.Instance == null ? new AssistStatePublisher.CalibrationSample[0]
            : AssistStatePublisher.Instance.Calibration.ToArray();
        session.ended_at = DateTime.UtcNow.ToString("O");
        session.shots = score.ShotsFired;
        session.hits = score.Hits;
        session.misses = score.Misses;
        session.accuracy = score.AccuracyPercentage;
        session.avg_reaction_ms = score.AverageReactionTime * 1000f;

        // JsonUtility escapes all data. Compose the array separately so each
        // runtime shot type includes only its available optional fields.
        string header = JsonUtility.ToJson(session, true);
        StringBuilder json = new StringBuilder(header.Substring(0, header.Length - 1));
        json.Append(",\n\"shots_detail\": [");
        for (int i = 0; i < shots.Count; i++)
        {
            if (i > 0) json.Append(',');
            json.Append('\n').Append(JsonUtility.ToJson(shots[i]));
        }
        json.Append("\n]\n}");

        string directory = Path.Combine(Application.persistentDataPath, "session_logs");
        string path = Path.Combine(directory, session.session_id + ".json");
        string temporaryPath = path + ".tmp";
        try
        {
            Directory.CreateDirectory(directory);
            File.WriteAllText(temporaryPath, json.ToString(), new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(temporaryPath, path, null);
            else File.Move(temporaryPath, path);
            Debug.Log("Session JSON saved: " + path);
            return path;
        }
        catch (Exception exception)
        {
            // Export failure must never break the summary or gameplay flow.
            Debug.LogError("Could not save session JSON at " + path + ": " + exception.Message);
            return null;
        }
    }
}
