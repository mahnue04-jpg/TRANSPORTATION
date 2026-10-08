(function () {
  "use strict";

  var audio = document.getElementById("narration");
  var video = document.getElementById("genova-video");
  var frame = document.getElementById("demo-frame");
  var caption = document.getElementById("caption-bar");
  var sceneTitle = document.getElementById("scene-title");
  var openScene = document.getElementById("open-scene");
  var currentTime = document.getElementById("current-time");
  var progress = document.getElementById("progress-bar");
  var startBtn = document.getElementById("start-demo");
  var pauseBtn = document.getElementById("pause-demo");
  var restartBtn = document.getElementById("restart-demo");
  var shareBtn = document.getElementById("share-demo");
  var copyBtn = document.getElementById("copy-demo-link");
  var shareStatus = document.getElementById("share-status");

  var cues = [
    { start: 0.00, end: 4.58, text: "Meet AMICOR Nova, your AI operations workspace built" },
    { start: 4.58, end: 7.78, text: "to help small businesses move faster while staying" },
    { start: 7.78, end: 8.48, text: "in control." },
    { start: 9.72, end: 13.34, text: "Nova Today brings priorities, approvals, and the AI" },
    { start: 13.34, end: 15.32, text: "assistant into one command center." },
    { start: 16.40, end: 19.32, text: "Workspace keeps ongoing work organized so you can" },
    { start: 19.32, end: 21.12, text: "continue where you left off." },
    { start: 21.44, end: 24.72, text: "The Operations Agent turns business requests into clear" },
    { start: 24.72, end: 27.98, text: "next steps, drafts, and owner-reviewed execution." },
    { start: 27.98, end: 32.56, text: "Work and Revenue helps surface opportunities, prepare applications," },
    { start: 33.12, end: 34.98, text: "and track the path from lead to paid" },
    { start: 34.98, end: 35.30, text: "work." },
    { start: 36.00, end: 40.58, text: "Government, Business, Communications, and Accounting bring research, operations," },
    { start: 40.58, end: 44.30, text: "follow-up, and financial visibility into the same ecosystem." },
    { start: 45.14, end: 49.24, text: "Creative Studio helps create scripts, images, voice, presenter" },
    { start: 49.24, end: 50.64, text: "media, and marketing assets." },
    { start: 51.34, end: 54.30, text: "AMICOR Nova gives you practical AI help across" },
    { start: 54.30, end: 56.92, text: "the workday, while you keep the final say." },
    { start: 56.92, end: 59.58, text: "Start with AMICOR Nova today." }
  ];

  var scenes = [
    { start: 0.00, route: "/nova", title: "Nova Home", label: "00:00–00:09" },
    { start: 9.00, route: "/nova/today", title: "Nova Today", label: "00:09–00:16" },
    { start: 16.00, route: "/nova/workspace", title: "Nova Workspace", label: "00:16–00:21" },
    { start: 21.00, route: "/nova/anonymous-operations", title: "Operations Agent", label: "00:21–00:28" },
    { start: 28.00, route: "/nova/work", title: "Work & Revenue", label: "00:28–00:36" },
    { start: 36.00, route: "/nova/government", title: "Government · Business · Communications · Accounting", label: "00:36–00:45" },
    { start: 45.00, route: "/nova/creative", title: "Creative Studio", label: "00:45–00:51" },
    { start: 51.00, route: "/nova", title: "AMICOR Nova Ecosystem", label: "00:51–00:57" },
    { start: 57.00, route: "/nova", title: "Start with AMICOR Nova", label: "00:57–01:00" }
  ];

  var activeScene = -1;

  function fmt(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }

  function cueFor(t) {
    for (var i = cues.length - 1; i >= 0; i--) {
      if (t >= cues[i].start && t <= cues[i].end + 0.35) return cues[i];
    }
    return null;
  }

  function sceneFor(t) {
    var index = 0;
    for (var i = scenes.length - 1; i >= 0; i--) {
      if (t >= scenes[i].start) { index = i; break; }
    }
    return index;
  }

  function renderSceneList() {
    var target = document.getElementById("scene-list");
    target.innerHTML = scenes.map(function (scene, i) {
      return "<li class=\"scene-row" + (i === activeScene ? " active" : "") + "\"><strong>" +
        scene.title + "</strong><span>" + scene.label + "</span></li>";
    }).join("");
  }

  function applyScene(index) {
    if (index === activeScene) return;
    activeScene = index;
    var scene = scenes[index];
    frame.src = scene.route;
    sceneTitle.textContent = scene.title;
    openScene.href = scene.route;
    renderSceneList();
  }

  function update() {
    var t = audio.currentTime || 0;
    var duration = audio.duration && isFinite(audio.duration) ? audio.duration : 60;
    currentTime.textContent = fmt(t);
    progress.style.width = Math.min(100, (t / duration) * 100) + "%";
    var cue = cueFor(t);
    if (cue) caption.textContent = cue.text;
    applyScene(sceneFor(t));
  }

  function play() {
    audio.play().then(function () {
      video.play().catch(function () {});
      startBtn.textContent = "Playing";
      startBtn.disabled = true;
      pauseBtn.disabled = false;
    }).catch(function () {
      startBtn.textContent = "Tap again to play";
    });
  }

  function pause() {
    audio.pause();
    video.pause();
    startBtn.textContent = "Resume demo";
    startBtn.disabled = false;
    pauseBtn.disabled = true;
  }

  function restart() {
    audio.pause();
    audio.currentTime = 0;
    video.currentTime = 0;
    applyScene(0);
    update();
    play();
  }

  audio.addEventListener("timeupdate", update);
  audio.addEventListener("play", update);
  audio.addEventListener("ended", function () {
    update();
    video.pause();
    startBtn.textContent = "Play again";
    startBtn.disabled = false;
    pauseBtn.disabled = true;
  });
  audio.addEventListener("loadedmetadata", update);

  startBtn.addEventListener("click", play);
  pauseBtn.addEventListener("click", pause);
  restartBtn.addEventListener("click", restart);

  function canonicalDemoUrl() {
    return window.location.origin + "/nova/one-minute-demo";
  }

  async function copyDemoLink() {
    var url = canonicalDemoUrl();
    try {
      await navigator.clipboard.writeText(url);
      if (shareStatus) shareStatus.textContent = "Demo link copied. Use it in proposals, applications, email, TikTok, Instagram, LinkedIn, and client outreach.";
    } catch (err) {
      if (shareStatus) shareStatus.textContent = url;
    }
  }

  if (copyBtn) copyBtn.addEventListener("click", copyDemoLink);
  if (shareBtn) shareBtn.addEventListener("click", async function () {
    var payload = {
      title: "AMICOR Nova — 60-Second Product Demo",
      text: "See AMICOR Nova in 60 seconds: AI operations, Work & Revenue, Government, Creative Studio, and more.",
      url: canonicalDemoUrl()
    };
    if (navigator.share) {
      try {
        await navigator.share(payload);
        if (shareStatus) shareStatus.textContent = "Demo share opened.";
        return;
      } catch (err) {}
    }
    await copyDemoLink();
  });

  applyScene(0);
  renderSceneList();
  update();
})();