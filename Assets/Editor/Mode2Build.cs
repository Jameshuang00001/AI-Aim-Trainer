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
            assist.Command(true, 4, "proximity");
            if (!assist.Armed || !assist.ProximityAssist) throw new System.Exception("Proximity mode selection failed");
            assist.Stop(); assist.Command(true, 4, "proximity");
            if (assist.Armed) throw new System.Exception("Proximity mode rearmed after Stop");
            assist.Command(true, 5, "hold");
            if (!assist.Armed || assist.ProximityAssist) throw new System.Exception("Hold mode selection failed");
            assist.Command(true, 5, "hold", 3f, 15f);
            if (assist.AssistSpeed != 15f) throw new System.Exception("Live speed was not applied");
            assist.Stop(); assist.Command(true, 5, "hold", 3f, 120f);
            if (assist.Armed) throw new System.Exception("Speed change rearmed stopped assistance");
            var quiet = typeof(AssistStatePublisher).GetMethod("MouseIsQuiet", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            if ((bool)quiet.Invoke(assist, new object[] { new UnityEngine.Vector2(0.001f, 0f), 10d }))
                throw new System.Exception("Moving mouse accepted");
            if ((bool)quiet.Invoke(assist, new object[] { UnityEngine.Vector2.zero, 10.1d }))
                throw new System.Exception("Mouse quiet interval too short accepted");
            if (!(bool)quiet.Invoke(assist, new object[] { UnityEngine.Vector2.zero, 10.16d }))
                throw new System.Exception("Still mouse rejected");
            if ((bool)quiet.Invoke(assist, new object[] { new UnityEngine.Vector2(0f, -0.001f), 10.17d }))
                throw new System.Exception("Mouse restart did not interrupt");
            CheckProximityZone(assist);
            UnityEngine.Debug.Log("Mode2 safety and proximity-zone checks passed");
        }
        finally { UnityEngine.Object.DestroyImmediate(owner); }
    }
    private static void CheckProximityZone(AssistStatePublisher assist)
    {
        var cameraObject = new UnityEngine.GameObject("Proximity test camera");
        var targetObject = new UnityEngine.GameObject("Proximity test target");
        var wall = UnityEngine.GameObject.CreatePrimitive(UnityEngine.PrimitiveType.Cube);
        try
        {
            var camera = cameraObject.AddComponent<UnityEngine.Camera>();
            camera.transform.position = new UnityEngine.Vector3(10000,10000,10000);
            var target = targetObject.AddComponent<Target>();
            typeof(Target).GetProperty("IsHittable").SetValue(target, true);
            var collider = targetObject.AddComponent<UnityEngine.SphereCollider>();
            collider.radius = 0.1f; collider.isTrigger = true;
            var zone = targetObject.AddComponent<HitZone>();
            typeof(HitZone).GetField("zone", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).SetValue(zone, HitZoneType.Head);
            var find = typeof(AssistStatePublisher).GetMethod("FindHead", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            wall.transform.position = camera.transform.position + new UnityEngine.Vector3(0,0,5);
            wall.SetActive(false);
            targetObject.transform.position = camera.transform.position + UnityEngine.Quaternion.Euler(0,2,0) * UnityEngine.Vector3.forward * 10;
            UnityEngine.Physics.SyncTransforms();
            if ((HitZone)find.Invoke(assist, new object[] {camera, null, 3f}) != zone)
                throw new System.Exception("Head inside proximity zone was rejected");
            if (find.Invoke(assist, new object[] {camera, null, 1f}) != null)
                throw new System.Exception("Head outside proximity zone was accepted");
            wall.transform.localScale = new UnityEngine.Vector3(3,3,0.2f); wall.SetActive(true);
            UnityEngine.Physics.SyncTransforms();
            if (find.Invoke(assist, new object[] {camera, null, 3f}) != null)
                throw new System.Exception("Occluded head was accepted");
            wall.SetActive(false); collider.enabled = false; UnityEngine.Physics.SyncTransforms();
            if (find.Invoke(assist, new object[] {camera, null, 3f}) != null)
                throw new System.Exception("Disabled head was accepted");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(cameraObject);
            UnityEngine.Object.DestroyImmediate(targetObject);
            UnityEngine.Object.DestroyImmediate(wall);
        }
    }
    public static void Build()
    {
        CheckSafety();
        PlayerSettings.resizableWindow = true;
        System.IO.Directory.CreateDirectory("Assets/StreamingAssets");
        // Portable builds must not contain a developer-machine path.
        System.IO.File.WriteAllText("Assets/StreamingAssets/coach-root.txt", "");
        AssetDatabase.Refresh();
        var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0) scenes = new[] { "Assets/Scenes/SampleScene.unity" };
        var report = BuildPipeline.BuildPlayer(scenes, "build/Mode2/AI-Aim-Trainer.app", BuildTarget.StandaloneOSX, BuildOptions.None);
        if (report.summary.result != BuildResult.Succeeded) throw new System.Exception("macOS build failed: " + report.summary.result);
    }
}
