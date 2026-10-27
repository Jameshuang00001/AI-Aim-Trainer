using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

// One-time, reproducible authoring of original primitive artwork. No gameplay code changes.
public static class OriginalArtPreview
{
    const string Root = "Assets/OriginalArt";
    [InitializeOnLoadMethod] static void Register()
    { EditorApplication.update -= Process; EditorApplication.update += Process; }
    static void Process()
    {
        const string bright = "Temp/OriginalArtBright.request";
        if(File.Exists(bright) && !EditorApplication.isCompiling && !EditorApplication.isUpdating && !EditorApplication.isPlayingOrWillChangePlaymode)
        {
            File.Delete(bright);
            try { Brighten(); File.WriteAllText("Temp/OriginalArtBright.result","Success"); }
            catch(Exception e) { Debug.LogException(e); File.WriteAllText("Temp/OriginalArtBright.result",e.ToString()); }
        }
        const string polish = "Temp/OriginalArtPolish.request";
        if (File.Exists(polish) && !EditorApplication.isCompiling && !EditorApplication.isUpdating && !EditorApplication.isPlayingOrWillChangePlaymode)
        {
            File.Delete(polish);
            try { RestoreOriginalFlash(); File.WriteAllText("Temp/OriginalArtPolish.result", "Success"); }
            catch(Exception e) { Debug.LogException(e); File.WriteAllText("Temp/OriginalArtPolish.result", e.ToString()); }
        }
        const string request = "Temp/OriginalArt.request";
        if (!File.Exists(request) || EditorApplication.isCompiling || EditorApplication.isUpdating || EditorApplication.isPlayingOrWillChangePlaymode) return;
        File.Delete(request);
        try { Create(); File.WriteAllText("Temp/OriginalArt.result", "Success"); }
        catch (Exception e) { Debug.LogException(e); File.WriteAllText("Temp/OriginalArt.result", e.ToString()); }
    }
    static Material Material(string name, Color color, Color emission = default(Color))
    {
        var mat = new Material(Shader.Find("Standard")); mat.name = name;
        mat.color = color; mat.SetFloat("_Glossiness", .25f);
        if (emission.maxColorComponent > 0) { mat.EnableKeyword("_EMISSION"); mat.SetColor("_EmissionColor", emission); }
        AssetDatabase.CreateAsset(mat, Root + "/" + name + ".mat"); return mat;
    }
    static GameObject Part(string name, PrimitiveType type, Transform parent, Vector3 position, Vector3 scale, Material mat, bool collision = false)
    {
        var go = GameObject.CreatePrimitive(type); go.name = name;
        go.transform.SetParent(parent, false); go.transform.localPosition = position; go.transform.localScale = scale;
        go.GetComponent<Renderer>().sharedMaterial = mat;
        if (!collision) UnityEngine.Object.DestroyImmediate(go.GetComponent<Collider>());
        return go;
    }
    static void Zone(GameObject go, Target owner, int type)
    {
        go.GetComponent<Collider>().isTrigger = true;
        var zone = new SerializedObject(go.AddComponent<HitZone>());
        zone.FindProperty("zone").enumValueIndex = type;
        zone.FindProperty("targetParent").objectReferenceValue = owner; zone.ApplyModifiedPropertiesWithoutUndo();
    }
    static AnimationClip Clip(string name, bool loop)
    {
        var clip = new AnimationClip { name = name, frameRate = 30 };
        var settings = AnimationUtility.GetAnimationClipSettings(clip); settings.loopTime = loop;
        AnimationUtility.SetAnimationClipSettings(clip, settings);
        AssetDatabase.CreateAsset(clip, Root + "/" + name + ".anim"); return clip;
    }
    static void Curve(AnimationClip clip, string path, string property, params Keyframe[] keys)
    { AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), property), new AnimationCurve(keys)); }
    static AnimatorController Controller()
    {
        var idle = Clip("DummyIdle", true); Curve(idle, "Torso", "localEulerAnglesRaw.x", new Keyframe(0,0),new Keyframe(1,0));
        var walk = Clip("DummyWalk", true);
        foreach (string limb in new[]{"LeftLeg","RightLeg","LeftArm","RightArm"})
        {
            float sign = limb == "LeftLeg" || limb == "RightArm" ? 1 : -1;
            Curve(walk,limb,"localEulerAnglesRaw.x",new Keyframe(0,-18*sign),new Keyframe(.25f,18*sign),new Keyframe(.5f,-18*sign));
        }
        var death = Clip("DummyFall", false);
        Curve(death,"","localEulerAnglesRaw.z",new Keyframe(0,0),new Keyframe(.6f,85),new Keyframe(1.5f,85));
        var controller = AnimatorController.CreateAnimatorControllerAtPath(Root + "/Dummy.controller");
        controller.AddParameter("IsMoving",AnimatorControllerParameterType.Bool); controller.AddParameter("Death",AnimatorControllerParameterType.Trigger);
        var machine=controller.layers[0].stateMachine;
        var i=machine.AddState("Idle"); i.motion=idle; machine.defaultState=i;
        var w=machine.AddState("Walk"); w.motion=walk;
        var d=machine.AddState("Fall"); d.motion=death;
        var iw=i.AddTransition(w); iw.hasExitTime=false; iw.duration=.12f; iw.AddCondition(AnimatorConditionMode.If,0,"IsMoving");
        var wi=w.AddTransition(i); wi.hasExitTime=false; wi.duration=.12f; wi.AddCondition(AnimatorConditionMode.IfNot,0,"IsMoving");
        var fall=machine.AddAnyStateTransition(d); fall.hasExitTime=false; fall.duration=.08f; fall.canTransitionToSelf=false; fall.AddCondition(AnimatorConditionMode.If,0,"Death");
        return controller;
    }
    static void RestoreOriginalFlash()
    {
        var weapon=UnityEngine.Object.FindObjectOfType<WeaponViewModel>();
        var existing=weapon.transform.Find("OriginalMuzzleFlash");
        GameObject flash=existing!=null ? existing.gameObject : Part("OriginalMuzzleFlash",PrimitiveType.Sphere,weapon.transform,new Vector3(0,.025f,.46f),new Vector3(.07f,.07f,.12f),AssetDatabase.LoadAssetAtPath<Material>(Root+"/Amber.mat"));
        flash.SetActive(false);
        var wp=new SerializedObject(weapon);wp.FindProperty("muzzleFlash").objectReferenceValue=flash;wp.ApplyModifiedPropertiesWithoutUndo();
        var labels=new[]{"ShotsText","HitsText","MissesText","AccuracyText","ReactionText","TimeText","ModeText","InstructionText","FPSText","CrosshairText"};
        foreach(var text in UnityEngine.Object.FindObjectsOfType<UnityEngine.UI.Text>(true))
            if(labels.Contains(text.name))text.color=new Color(.9f,.96f,1f);
        var scene=weapon.gameObject.scene;EditorSceneManager.MarkSceneDirty(scene);EditorSceneManager.SaveScene(scene);
    }
    [MenuItem("Tools/Original Art/Bright Range and Detailed Dummy")]
    public static void Brighten()
    {
        var scene=SceneManager.GetActiveScene();
        if(scene.isDirty)throw new InvalidOperationException("Save scene edits before applying art revision.");
        AssetDatabase.LoadAssetAtPath<Material>(Root+"/Floor.mat").color=new Color(.74f,.76f,.78f);
        AssetDatabase.LoadAssetAtPath<Material>(Root+"/Wall.mat").color=new Color(.86f,.88f,.9f);
        foreach(var mat in new[]{AssetDatabase.LoadAssetAtPath<Material>(Root+"/Floor.mat"),AssetDatabase.LoadAssetAtPath<Material>(Root+"/Wall.mat")})EditorUtility.SetDirty(mat);
        var art=GameObject.Find("OriginalTrainingRange");
        foreach(Transform t in art.transform.Cast<Transform>().ToArray())
            if(new[]{"FloorLane","DistanceLine","DistanceMarker","FiringLine","WallGuide","BackWallPanel","BackWallLight"}.Contains(t.name))UnityEngine.Object.DestroyImmediate(t.gameObject);
        RenderSettings.ambientLight=new Color(.32f,.35f,.39f);
        RenderSettings.ambientIntensity=1f;
        QualitySettings.shadows=ShadowQuality.All;
        QualitySettings.shadowDistance=100f;QualitySettings.shadowResolution=ShadowResolution.High;QualitySettings.shadowCascades=4;
        var backdrop=art.transform.Find("WhiteBackWall");
        if(backdrop==null)Part("WhiteBackWall",PrimitiveType.Cube,art.transform,new Vector3(0,10,70.2f),new Vector3(80,20,.3f),AssetDatabase.LoadAssetAtPath<Material>(Root+"/Wall.mat"));
        Camera.main.backgroundColor=new Color(.88f,.91f,.94f);
        var light=UnityEngine.Object.FindObjectOfType<Light>();if(light!=null){light.color=Color.white;light.intensity=1.05f;light.shadows=LightShadows.Soft;light.shadowStrength=.9f;light.shadowBias=.03f;light.shadowNormalBias=.1f;light.transform.rotation=Quaternion.Euler(48,-25,0);}
        var labels=new[]{"ShotsText","HitsText","MissesText","AccuracyText","ReactionText","TimeText","ModeText","InstructionText","FPSText"};
        foreach(var text in UnityEngine.Object.FindObjectsOfType<UnityEngine.UI.Text>(true))
        {
            if(labels.Contains(text.name))text.color=new Color(.06f,.09f,.12f);
            if(text.name=="CrosshairText")
            {
                text.color=new Color(.03f,.03f,.03f);text.fontSize=Mathf.Max(text.fontSize,22);
                var outline=text.GetComponent<UnityEngine.UI.Outline>()??text.gameObject.AddComponent<UnityEngine.UI.Outline>();
                outline.effectColor=Color.white;outline.effectDistance=new Vector2(1,-1);
            }
        }
        var prefab=PrefabUtility.LoadPrefabContents("Assets/Prefabs/EnemyTarget.prefab");
        try {
            prefab.transform.localScale=Vector3.one*1.55f;
            var visual=prefab.transform.Find("OriginalDummy");
            var texture=AssetDatabase.LoadAssetAtPath<Texture2D>(Root+"/DetailTint.asset");
            if(texture==null){texture=new Texture2D(2,2);texture.SetPixels(new[]{new Color(.07f,.09f,.12f),new Color(.07f,.09f,.12f),new Color(.07f,.09f,.12f),new Color(.07f,.09f,.12f)});texture.Apply();AssetDatabase.CreateAsset(texture,Root+"/DetailTint.asset");}
            var detail=AssetDatabase.LoadAssetAtPath<Material>(Root+"/Detail.mat");
            if(detail==null){detail=Material("Detail",Color.white);detail.mainTexture=texture;EditorUtility.SetDirty(detail);}
            var body=AssetDatabase.LoadAssetAtPath<Material>(Root+"/Dummy.mat");
            var old=visual.Find("DetailParts");if(old!=null)UnityEngine.Object.DestroyImmediate(old.gameObject);
            var extras=new GameObject("DetailParts");extras.transform.SetParent(visual,false);
            Part("ChestPlate",PrimitiveType.Cube,extras.transform,new Vector3(0,1.19f,.15f),new Vector3(.31f,.30f,.06f),body);
            Part("ChestInset",PrimitiveType.Cube,extras.transform,new Vector3(0,1.21f,.19f),new Vector3(.18f,.08f,.025f),detail);
            Part("WaistJoint",PrimitiveType.Cylinder,extras.transform,new Vector3(0,.88f,0),new Vector3(.28f,.06f,.28f),detail);
            Part("Pelvis",PrimitiveType.Cube,extras.transform,new Vector3(0,.80f,0),new Vector3(.34f,.19f,.27f),body);
            Part("Neck",PrimitiveType.Cylinder,extras.transform,new Vector3(0,1.45f,0),new Vector3(.16f,.05f,.16f),detail);
            var head=visual.Find("Head");
            var visor=head.Find("Visor");if(visor!=null){visor.GetComponent<Renderer>().sharedMaterial=detail;visor.localScale=new Vector3(.78f,.23f,.18f);}
            foreach(float side in new[]{-1f,1f})
            {
                string prefix=side<0?"Left":"Right";
                Part(prefix+"Shoulder",PrimitiveType.Sphere,extras.transform,new Vector3(side*.32f,1.38f,0),new Vector3(.25f,.23f,.27f),body);
                var arm=visual.Find(prefix+"Arm");
                var oldArm=arm.Find("ArmDetails");if(oldArm!=null)UnityEngine.Object.DestroyImmediate(oldArm.gameObject);
                var armDetails=new GameObject("ArmDetails");armDetails.transform.SetParent(arm,false);
                Part("ElbowJoint",PrimitiveType.Sphere,armDetails.transform,new Vector3(0,-.28f,0),Vector3.one*.16f,detail);
                Part("ForearmShell",PrimitiveType.Cube,armDetails.transform,new Vector3(0,-.44f,.015f),new Vector3(.18f,.23f,.17f),body);
                Part("Hand",PrimitiveType.Cube,armDetails.transform,new Vector3(0,-.64f,.025f),new Vector3(.14f,.15f,.16f),detail);
                var leg=visual.Find(prefix+"Leg");
                var oldLeg=leg.Find("LegDetails");if(oldLeg!=null)UnityEngine.Object.DestroyImmediate(oldLeg.gameObject);
                var legDetails=new GameObject("LegDetails");legDetails.transform.SetParent(leg,false);
                Part("KneeJoint",PrimitiveType.Sphere,legDetails.transform,new Vector3(0,-.35f,.005f),Vector3.one*.19f,detail);
                Part("KneePad",PrimitiveType.Cube,legDetails.transform,new Vector3(0,-.35f,.11f),new Vector3(.19f,.18f,.06f),body);
                Part("ShinPlate",PrimitiveType.Cube,legDetails.transform,new Vector3(0,-.57f,.065f),new Vector3(.16f,.22f,.08f),body);
            }
            foreach(var renderer in visual.GetComponentsInChildren<Renderer>())
            {
                renderer.sharedMaterial=body;renderer.shadowCastingMode=UnityEngine.Rendering.ShadowCastingMode.On;renderer.receiveShadows=true;
            }
            PrefabUtility.SaveAsPrefabAsset(prefab,"Assets/Prefabs/EnemyTarget.prefab");
        }finally{PrefabUtility.UnloadPrefabContents(prefab);}
        EditorSceneManager.MarkSceneDirty(scene);EditorSceneManager.SaveScene(scene);AssetDatabase.SaveAssets();
    }
    [MenuItem("Tools/Original Art/Create Preview")]
    public static void Create()
    {
        if (AssetDatabase.IsValidFolder(Root)) throw new InvalidOperationException("OriginalArt already exists; restore backup before rerunning migration.");
        var scene=SceneManager.GetActiveScene();
        if (scene.path != "Assets/Scenes/SampleScene.unity") scene=EditorSceneManager.OpenScene("Assets/Scenes/SampleScene.unity");
        if (scene.isDirty) throw new InvalidOperationException("Save or discard existing scene edits before migration.");
        AssetDatabase.CreateFolder("Assets","OriginalArt");
        var navy=Material("Navy",new Color(.055f,.09f,.14f));
        var wall=Material("Wall",new Color(.17f,.23f,.3f));
        var floor=Material("Floor",new Color(.10f,.15f,.20f));
        var trim=Material("Cyan",new Color(.04f,.62f,.74f),new Color(.02f,.22f,.3f));
        var warm=Material("Amber",new Color(.9f,.49f,.1f),new Color(.35f,.11f,.01f));
        var dummy=Material("Dummy",Color.white);
        var head=Material("Head",Color.white,new Color(.13f,.10f,.015f));
        // Remove only instances sourced from the retired imported scene/arms models.
        var imported = UnityEngine.Object.FindObjectsOfType<Transform>(true)
            .Select(t=>PrefabUtility.GetOutermostPrefabInstanceRoot(t.gameObject)).Where(g=>g!=null).Distinct()
            .Where(g=>{var p=PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(g); return p.StartsWith("Assets/Models/Environment/Venator/") || p.StartsWith("Assets/Models/FPSViewModel/Arms/");}).ToArray();
        foreach(var go in imported) UnityEngine.Object.DestroyImmediate(go);
        foreach(var filter in UnityEngine.Object.FindObjectsOfType<MeshFilter>(true).ToArray())
        {
            string path=AssetDatabase.GetAssetPath(filter.sharedMesh);
            if(path.StartsWith("Assets/Models/Environment/Venator/") || path.StartsWith("Assets/Models/FPSViewModel/Arms/")) UnityEngine.Object.DestroyImmediate(filter.gameObject);
        }
        // Keep original arena colliders, player, spawn center and platform dimensions.
        foreach(var renderer in UnityEngine.Object.FindObjectsOfType<MeshRenderer>(true))
            renderer.sharedMaterial=renderer.name=="Ground" || renderer.name=="ShootingPlatform" ? floor : wall;
        var art=new GameObject("OriginalTrainingRange");
        for(int x=-30;x<=30;x+=10)
            Part("FloorLane",PrimitiveType.Cube,art.transform,new Vector3(x,.014f,28),new Vector3(.045f,.018f,54),trim);
        for(int z=5;z<=65;z+=10)
        {
            Part("DistanceLine",PrimitiveType.Cube,art.transform,new Vector3(0,.018f,z),new Vector3(70,.018f,.035f),trim);
            var label=new GameObject("DistanceMarker");label.transform.SetParent(art.transform,false);label.transform.position=new Vector3(-9,.045f,z);
            label.transform.rotation=Quaternion.Euler(90,0,0);
            var text=label.AddComponent<TextMesh>();text.text=z+" m";text.fontSize=64;text.characterSize=.08f;text.color=new Color(.25f,.8f,.9f);text.anchor=TextAnchor.MiddleCenter;
        }
        for(int x=-35;x<=35;x+=10)
        {
            Part("BackWallPanel",PrimitiveType.Cube,art.transform,new Vector3(x,2.5f,69.75f),new Vector3(8,4,.08f),navy);
            Part("BackWallLight",PrimitiveType.Cube,art.transform,new Vector3(x,4.5f,69.65f),new Vector3(8,.07f,.05f),trim);
        }
        foreach(string name in new[]{"LeftWall","RightWall"})
        {
            var go=GameObject.Find(name);if(go!=null)Part("WallGuide",PrimitiveType.Cube,art.transform,new Vector3(go.transform.position.x*.995f,1.4f,22),new Vector3(.04f,.09f,78),trim);
        }
        Part("FiringLine",PrimitiveType.Cube,art.transform,new Vector3(0,.215f,.9f),new Vector3(70,.025f,.15f),warm);
        RenderSettings.ambientMode=UnityEngine.Rendering.AmbientMode.Flat;RenderSettings.ambientLight=new Color(.52f,.60f,.7f);
        RenderSettings.fog=false;RenderSettings.skybox=null;Camera.main.clearFlags=CameraClearFlags.SolidColor;Camera.main.backgroundColor=new Color(.045f,.07f,.11f);
        var light=UnityEngine.Object.FindObjectOfType<Light>();if(light!=null){light.color=new Color(.88f,.94f,1f);light.intensity=1.05f;light.transform.rotation=Quaternion.Euler(48,-25,0);}
        // Preserve Target settings, and retain Animator presence used by roaming/death gates.
        var old=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/EnemyTarget.prefab").GetComponent<Target>();
        var targetRoot=new GameObject("EnemyTarget");var target=targetRoot.AddComponent<Target>();EditorUtility.CopySerialized(old,target);
        var visual=new GameObject("OriginalDummy");visual.transform.SetParent(targetRoot.transform,false);
        var animator=visual.AddComponent<Animator>();animator.runtimeAnimatorController=Controller();animator.applyRootMotion=false;
        var torso=Part("Torso",PrimitiveType.Capsule,visual.transform,new Vector3(0,1.12f,0),new Vector3(.48f,.35f,.32f),dummy,true);Zone(torso,target,0);
        var h=Part("Head",PrimitiveType.Sphere,visual.transform,new Vector3(0,1.68f,0),new Vector3(.34f,.38f,.34f),head,true);Zone(h,target,1);
        Part("Visor",PrimitiveType.Cube,h.transform,new Vector3(0,.10f,.43f),new Vector3(.65f,.18f,.16f),navy);
        foreach(float side in new[]{-1f,1f})
        {
            string prefix=side<0?"Left":"Right";
            var leg=new GameObject(prefix+"Leg");leg.transform.SetParent(visual.transform,false);leg.transform.localPosition=new Vector3(side*.14f,.83f,0);
            var shin=Part("Shin",PrimitiveType.Capsule,leg.transform,new Vector3(0,-.38f,0),new Vector3(.17f,.38f,.19f),dummy,true);Zone(shin,target,0);
            var foot=Part("Foot",PrimitiveType.Cube,leg.transform,new Vector3(0,-.76f,.07f),new Vector3(.22f,.13f,.36f),dummy,true);Zone(foot,target,0);
            var arm=new GameObject(prefix+"Arm");arm.transform.SetParent(visual.transform,false);arm.transform.localPosition=new Vector3(side*.36f,1.38f,0);
            var forearm=Part("Forearm",PrimitiveType.Capsule,arm.transform,new Vector3(0,-.30f,0),new Vector3(.15f,.30f,.15f),dummy,true);Zone(forearm,target,0);
        }
        var targetProperties=new SerializedObject(target);targetProperties.FindProperty("targetAnimator").objectReferenceValue=animator;targetProperties.ApplyModifiedPropertiesWithoutUndo();
        var prefab=PrefabUtility.SaveAsPrefabAsset(targetRoot,"Assets/Prefabs/EnemyTarget.prefab");UnityEngine.Object.DestroyImmediate(targetRoot);
        var spawner=new SerializedObject(UnityEngine.Object.FindObjectOfType<TargetSpawner>());spawner.FindProperty("targetPrefab").objectReferenceValue=prefab;spawner.ApplyModifiedPropertiesWithoutUndo();
        // Primitive mechanical arms and blaster under the existing recoil component.
        var weapon=UnityEngine.Object.FindObjectOfType<WeaponViewModel>();
        foreach(Transform child in weapon.transform.Cast<Transform>().ToArray()) UnityEngine.Object.DestroyImmediate(child.gameObject);
        weapon.transform.localPosition=new Vector3(.18f,-.28f,.48f);weapon.transform.localRotation=Quaternion.identity;weapon.transform.localScale=Vector3.one;
        Part("BlasterBody",PrimitiveType.Cube,weapon.transform,new Vector3(0,0,.13f),new Vector3(.11f,.13f,.38f),navy);
        Part("Barrel",PrimitiveType.Cube,weapon.transform,new Vector3(0,.025f,.37f),new Vector3(.065f,.065f,.15f),wall);
        Part("BarrelAccent",PrimitiveType.Cube,weapon.transform,new Vector3(0,.065f,.37f),new Vector3(.04f,.012f,.12f),trim);
        var grip=Part("Grip",PrimitiveType.Cube,weapon.transform,new Vector3(0,-.105f,.035f),new Vector3(.075f,.18f,.11f),wall);grip.transform.localRotation=Quaternion.Euler(-12,0,0);
        Part("RightMechanicalHand",PrimitiveType.Cube,weapon.transform,new Vector3(.015f,-.12f,.03f),new Vector3(.10f,.09f,.14f),trim);
        var ra=Part("RightMechanicalArm",PrimitiveType.Capsule,weapon.transform,new Vector3(.07f,-.21f,-.16f),new Vector3(.085f,.18f,.085f),wall);ra.transform.localRotation=Quaternion.Euler(60,-10,0);
        Part("LeftMechanicalHand",PrimitiveType.Cube,weapon.transform,new Vector3(-.09f,-.07f,.18f),new Vector3(.08f,.08f,.13f),trim);
        var la=Part("LeftMechanicalArm",PrimitiveType.Capsule,weapon.transform,new Vector3(-.20f,-.19f,-.015f),new Vector3(.08f,.18f,.08f),wall);la.transform.localRotation=Quaternion.Euler(52,32,-25);
        RestoreOriginalFlash();
        EditorSceneManager.MarkSceneDirty(scene);EditorSceneManager.SaveScene(scene);AssetDatabase.SaveAssets();
        // Verify active scene/prefab dependencies before moving old art out of Assets.
        var prohibited=new[]{"Assets/Models/Environment/Venator/","Assets/Models/EnemyHumanoid/","Assets/Models/FPSViewModel/","Assets/Animations/EnemyHumanoid/","Assets/Textures/Environment/Venator/","Assets/Textures/FPSViewModel/"};
        var dependencies=AssetDatabase.GetDependencies(new[]{scene.path,"Assets/Prefabs/EnemyTarget.prefab"},true);
        var bad=dependencies.Where(p=>prohibited.Any(prefix=>p.StartsWith(prefix))).ToArray();
        if(bad.Length>0)throw new InvalidOperationException("Imported-art references remain: "+string.Join(",",bad));
        var backup="LocalArtBackup/20261027";Directory.CreateDirectory(backup);
        foreach(string path in new[]{"Assets/Models","Assets/Animations","Assets/Textures","Assets/Materials/Venator","Assets/Materials/FPSViewModel","Assets/Materials/arms.mat","Assets/Materials/pistol.mat"})
        {
            string dest=Path.Combine(backup,path);Directory.CreateDirectory(Path.GetDirectoryName(dest));
            if(Directory.Exists(path))Directory.Move(path,dest);else if(File.Exists(path))File.Move(path,dest);
            if(File.Exists(path+".meta"))File.Move(path+".meta",dest+".meta");
        }
        AssetDatabase.Refresh();Brighten();Debug.Log("Original primitive art created; imported assets retained outside Assets. Gameplay scripts unchanged.");
    }
}
