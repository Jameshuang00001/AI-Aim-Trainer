using UnityEditor;
using UnityEditor.Build.Reporting;
using System.Linq;
public static class Mode2Build
{
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
            assist.SetLocal(true);
            assist.Command(false, 3);
            if (!assist.Armed) throw new System.Exception("Idle Coach overrode local Start");
            UnityEngine.Debug.Log("Mode2 safety checks passed");
        }
        finally { UnityEngine.Object.DestroyImmediate(owner); }
    }
    public static void Build()
    {
        CheckSafety();
        var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0) scenes = new[] { "Assets/Scenes/SampleScene.unity" };
        var report = BuildPipeline.BuildPlayer(scenes, "build/Mode2/AI-Aim-Trainer.app", BuildTarget.StandaloneOSX, BuildOptions.None);
        if (report.summary.result != BuildResult.Succeeded) throw new System.Exception("macOS build failed: " + report.summary.result);
    }
}
