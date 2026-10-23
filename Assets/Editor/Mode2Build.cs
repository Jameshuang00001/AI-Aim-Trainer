using UnityEditor;
using UnityEditor.Build.Reporting;
using System.Linq;
public static class Mode2Build
{
    [InitializeOnLoadMethod]
    private static void RegisterBuildRequest()
    {
        EditorApplication.update -= ProcessBuildRequest;
        EditorApplication.update += ProcessBuildRequest;
    }
    private static void ProcessBuildRequest()
    {
        const string request = "Temp/Mode2Build.request";
        if (!System.IO.File.Exists(request) || EditorApplication.isPlayingOrWillChangePlaymode ||
            EditorApplication.isCompiling || EditorApplication.isUpdating) return;
        System.IO.File.Delete(request);
        try { Build(); System.IO.File.WriteAllText("Temp/Mode2Build.result", "Success"); }
        catch (System.Exception error)
        {
            UnityEngine.Debug.LogException(error);
            System.IO.File.WriteAllText("Temp/Mode2Build.result", error.ToString());
        }
    }
    private static void CheckSafety()
    {
        var owner = new UnityEngine.GameObject("Mode2 safety verification");
        try
        {
            var assist = owner.AddComponent<AssistStatePublisher>();
            assist.Command(true, 1);
            if (!assist.Armed) throw new System.Exception("Start failed");
            assist.Stop();
            assist.Command(true, 1);
            if (assist.Armed) throw new System.Exception("Emergency stop was rearmed by heartbeat");
            assist.Command(true, 2);
            if (!assist.Armed) throw new System.Exception("Explicit restart failed");
            assist.Command(false, 3);
            if (assist.Armed) throw new System.Exception("Remote Stop failed");
            assist.Command(true, 4, "shot");
            if (!assist.Armed || !assist.ShotCorrection) throw new System.Exception("Shot mode selection failed");
            assist.Stop(); assist.Command(true, 4, "shot");
            if (assist.Armed) throw new System.Exception("Shot mode rearmed after Stop");
            assist.Command(true, 5, "hold");
            if (!assist.Armed || assist.ShotCorrection) throw new System.Exception("Hold mode selection failed");
            UnityEngine.Debug.Log("Mode2 safety checks passed");
        }
        finally { UnityEngine.Object.DestroyImmediate(owner); }
    }
    public static void Build()
    {
        CheckSafety();
        System.IO.Directory.CreateDirectory("Assets/StreamingAssets");
        System.IO.File.WriteAllText("Assets/StreamingAssets/coach-root.txt", System.IO.Directory.GetCurrentDirectory());
        AssetDatabase.Refresh();
        var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0) scenes = new[] { "Assets/Scenes/SampleScene.unity" };
        var report = BuildPipeline.BuildPlayer(scenes, "build/Mode2/AI-Aim-Trainer.app", BuildTarget.StandaloneOSX, BuildOptions.None);
        if (report.summary.result != BuildResult.Succeeded) throw new System.Exception("macOS build failed: " + report.summary.result);
    }
}
