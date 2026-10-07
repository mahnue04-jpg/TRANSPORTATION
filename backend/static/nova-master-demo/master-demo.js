(function () {
  "use strict";

  var TOTAL_SECONDS = 30 * 60;
  var chapters = [
    {
      title: "Opening — What AMICOR Nova is",
      route: "/nova",
      start: 0, end: 90,
      caption: "Welcome to AMICOR Nova. Nova brings practical AI assistance into one owner-controlled workspace for everyday business operations.",
      summary: "Introduce AMICOR Nova, who it is for, and the owner-controlled approach. Genova appears as the guide while the live Nova home experience is visible."
    },
    {
      title: "Nova Home & Today",
      route: "/nova/today",
      start: 90, end: 210,
      caption: "Nova Today brings priorities, review items, approvals, and the AI assistant into one focused operating view.",
      summary: "Walk through Today, attention items, Review, Approve, Snooze, Dismiss, and the Ask Nova surface."
    },
    {
      title: "Nova Workspace",
      route: "/nova/workspace",
      start: 210, end: 330,
      caption: "Workspace keeps ongoing business work together so Nova can help continue the work instead of starting over every time.",
      summary: "Show how active work and saved context are organized inside Workspace."
    },
    {
      title: "Operations Agent",
      route: "/nova/anonymous-operations",
      start: 330, end: 540,
      caption: "The Operations Agent helps turn incoming work into organized next steps, drafts, reviews, and owner-controlled execution.",
      summary: "Demonstrate the Operations Agent workflow and keep any external action clearly subject to owner control."
    },
    {
      title: "Work & Revenue",
      route: "/nova/work",
      start: 540, end: 780,
      caption: "Work & Revenue is where Nova helps surface work opportunities and prepare the path from lead to approved submission.",
      summary: "Show the Nova Work experience, opportunity handling, preparation, and the difference between automated preparation and human-only blockers."
    },
    {
      title: "Communications",
      route: "/nova/communications",
      start: 780, end: 900,
      caption: "Communications helps organize messages and follow-up work so important conversations are easier to act on.",
      summary: "Show the Communications module and how communication work fits into Nova's broader operating system."
    },
    {
      title: "Government",
      route: "/nova/government",
      start: 900, end: 1020,
      caption: "Government organizes public-sector research, forms, compliance topics, certifications, and related business tasks.",
      summary: "Show the Government workspace without presenting unfinished or unverified functions as live."
    },
    {
      title: "Business",
      route: "/nova/business",
      start: 1020, end: 1140,
      caption: "Business gives owners a focused place for practical operating work, planning, and business support.",
      summary: "Demonstrate the live Business module and how it connects with the rest of Nova."
    },
    {
      title: "Accounting, Aging & Trends",
      route: "/nova/accounting",
      start: 1140, end: 1320,
      caption: "Nova's accounting views provide read-only financial visibility, aging views, and monthly trends while keeping financial execution separate.",
      summary: "Walk through Accounting summary, Aging, and Trends. Keep the read-only posture and test-mode indicators visible where applicable."
    },
    {
      title: "Creative Studio",
      route: "/nova/creative",
      start: 1320, end: 1500,
      caption: "Creative Studio plans scripts, storyboards, images, voice, presenter media, and review-ready marketing assets.",
      summary: "Show the actual Creative Studio used to create this demo, including the full-body Genova proof clip and owner-gated media generation."
    },
    {
      title: "Available now vs. expanding",
      route: "/nova",
      start: 1500, end: 1740,
      caption: "The demo distinguishes what is available now from capabilities that are still being expanded. Unfinished features are not presented as live products.",
      summary: "Owner-review chapter for product availability. Use only verified live modules in the 'available now' portion; keep roadmap items explicitly labeled as coming or expanding."
    },
    {
      title: "Closing — Start with AMICOR Nova",
      route: "/nova",
      start: 1740, end: 1800,
      caption: "AMICOR Nova is built to help owners move faster while staying in control. Start with AMICOR Nova today.",
      summary: "Close with the owner-controlled value proposition and final call to action."
    }
  ];

  var currentIndex = 0;
  var elapsed = 0;
  var timer = null;

  function $(id) { return document.getElementById(id); }

  function fmt(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function renderChapterList() {
    $("chapter-list").innerHTML = chapters.map(function (chapter, index) {
      return "<li><button class=\"chapter-button" + (index === currentIndex ? " active" : "") +
        "\" data-index=\"" + index + "\"><strong>" + (index + 1) + ". " + chapter.title +
        "</strong><span>" + fmt(chapter.start) + "–" + fmt(chapter.end) + "</span></button></li>";
    }).join("");
    Array.prototype.forEach.call(document.querySelectorAll(".chapter-button"), function (button) {
      button.addEventListener("click", function () {
        selectChapter(Number(button.getAttribute("data-index")), true);
      });
    });
  }

  function selectChapter(index, jumpTime) {
    currentIndex = Math.max(0, Math.min(chapters.length - 1, index));
    var chapter = chapters[currentIndex];
    if (jumpTime) elapsed = chapter.start;

    $("chapter-title").textContent = chapter.title;
    $("chapter-range").textContent = fmt(chapter.start) + "–" + fmt(chapter.end);
    $("chapter-heading").textContent = chapter.title;
    $("chapter-summary").textContent = chapter.summary;
    $("caption-bar").textContent = chapter.caption;
    $("product-frame").src = chapter.route;
    $("open-route").href = chapter.route;

    var video = $("presenter-video");
    try {
      video.currentTime = 0;
      video.play().catch(function () {});
    } catch (e) {}

    renderChapterList();
    renderProgress();
  }

  function renderProgress() {
    var pct = Math.min(100, Math.max(0, (elapsed / TOTAL_SECONDS) * 100));
    $("progress-bar").style.width = pct + "%";
    $("elapsed").textContent = fmt(elapsed);
    $("remaining").textContent = fmt(TOTAL_SECONDS - elapsed) + " remaining";
  }

  function chapterForTime(seconds) {
    for (var i = chapters.length - 1; i >= 0; i--) {
      if (seconds >= chapters[i].start) return i;
    }
    return 0;
  }

  function tick() {
    elapsed += 1;
    if (elapsed >= TOTAL_SECONDS) {
      elapsed = TOTAL_SECONDS;
      pause();
    }
    var nextIndex = chapterForTime(elapsed);
    if (nextIndex !== currentIndex) selectChapter(nextIndex, false);
    renderProgress();
  }

  function start() {
    if (timer) return;
    var video = $("presenter-video");
    video.play().catch(function () {});
    timer = window.setInterval(tick, 1000);
    $("start-demo").textContent = "Running";
  }

  function pause() {
    if (timer) window.clearInterval(timer);
    timer = null;
    $("presenter-video").pause();
    $("start-demo").textContent = "Resume guided demo";
  }

  $("start-demo").addEventListener("click", start);
  $("pause-demo").addEventListener("click", pause);
  $("prev-chapter").addEventListener("click", function () { selectChapter(currentIndex - 1, true); });
  $("next-chapter").addEventListener("click", function () { selectChapter(currentIndex + 1, true); });

  $("presenter-video").addEventListener("ended", function () {
    if (timer) {
      this.currentTime = 0;
      this.play().catch(function () {});
    }
  });

  selectChapter(0, true);
})();