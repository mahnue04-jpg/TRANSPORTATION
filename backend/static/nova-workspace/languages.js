/* Workspace interface translations. Saved user content is never rewritten. */
(function () {
  'use strict';
  var rows = [
    ['Screen language','Luqadda shaashadda','لغة الشاشة','Langue de l’écran','Idioma de pantalla'],
    ['Nova Workspace','Goobta shaqada Nova','مساحة عمل Nova','Espace de travail Nova','Espacio de trabajo Nova'],
    ['Nova Home','Bogga hore Nova','الرئيسية Nova','Accueil Nova','Inicio Nova'],
    ['Today','Maanta','اليوم','Aujourd’hui','Hoy'],
    ['Workspace','Goobta shaqada','مساحة العمل','Espace de travail','Espacio de trabajo'],
    ['Communications','Isgaarsiinta','الاتصالات','Communications','Comunicaciones'],
    ['Government','Dowladda','الحكومة','Administration','Gobierno'],
    ['Business','Ganacsiga','الأعمال','Entreprise','Negocios'],
    ['Accounting','Xisaabaadka','المحاسبة','Comptabilité','Contabilidad'],
    ['Aging','Da’da deynta','أعمار الديون','Ancienneté des créances','Antigüedad de saldos'],
    ['Trends','Isbeddellada','الاتجاهات','Tendances','Tendencias'],
    ['Web / Search','Internet / Raadinta','الويب / البحث','Web / Recherche','Web / Buscar'],
    ['Files','Faylasha','الملفات','Fichiers','Archivos'],
    ['Voice','Codka','الصوت','Voix','Voz'],
    ['Change the Workspace interface and default answer language. Saved documents keep their original wording.','Beddel luqadda goobta shaqada iyo jawaabta. Dukumentiyada kaydsan sidoodii ayay ahaanayaan.','غيّر لغة مساحة العمل ولغة الإجابة الافتراضية. تبقى المستندات المحفوظة بصيغتها الأصلية.','Changez la langue de l’interface et des réponses. Les documents enregistrés conservent leur texte original.','Cambie el idioma de la interfaz y las respuestas. Los documentos guardados conservan su texto original.'],
    ['AMICOR Nova master demo','Bandhigga AMICOR Nova','عرض AMICOR Nova','Démonstration AMICOR Nova','Demostración AMICOR Nova'],
    ['Use the 60-second demo as the standard product overview for prospects, partners, applications, and outreach.','Daawo bandhigga 60 ilbiriqsi si aad u barato badeecadda.','شاهد العرض لمدة 60 ثانية للتعرّف على المنتج.','Regardez la présentation de 60 secondes du produit.','Vea la presentación del producto de 60 segundos.'],
    ['Watch 60-second demo','Daawo bandhigga 60 ilbiriqsi','شاهد عرض 60 ثانية','Voir la démonstration de 60 secondes','Ver demostración de 60 segundos'],
    ['All workspace projects · Select a project below to work on it.','Mashruucyada oo dhan · Hoos ka dooro mashruuc.','جميع المشاريع · اختر مشروعًا أدناه للعمل عليه.','Tous les projets · Choisissez un projet ci-dessous.','Todos los proyectos · Seleccione un proyecto abajo.'],
    ['All workspace projects','Mashruucyada oo dhan','جميع المشاريع','Tous les projets','Todos los proyectos'],
    ['Selected project: {title}','Mashruuca la doortay: {title}','المشروع المحدد: {title}','Projet sélectionné : {title}','Proyecto seleccionado: {title}'],
    ['Search Nova Workspace','Raadi goobta shaqada Nova','ابحث في مساحة عمل Nova','Rechercher dans Nova','Buscar en Nova'],
    ['Search projects, files, and prior Nova work','Raadi mashruucyo, faylal iyo shaqadii hore','ابحث عن المشاريع والملفات والعمل السابق','Rechercher projets, fichiers et travaux précédents','Buscar proyectos, archivos y trabajo anterior'],
    ['Search workspace','Raadi goobta shaqada','ابحث في مساحة العمل','Rechercher','Buscar'],
    ['Ask Mrs. Nova Brain','Weydii Mrs. Nova Brain','اسأل Mrs. Nova Brain','Demander à Mrs. Nova Brain','Preguntar a Mrs. Nova Brain'],
    ['Ask Mrs. Nova Brain about this workspace','Weydii Nova wax ku saabsan shaqadan','اسأل Nova عن مساحة العمل هذه','Interrogez Nova sur cet espace de travail','Pregunte a Nova sobre este espacio'],
    ['Ask Nova to work on {title}','Weydii Nova inay ka shaqeyso {title}','اطلب من Nova العمل على {title}','Demandez à Nova de travailler sur {title}','Pida a Nova trabajar en {title}'],
    ['Ask Nova','Weydii Nova','اسأل Nova','Demander à Nova','Preguntar a Nova'],
    ['Answer and speech language','Luqadda jawaabta iyo codka','لغة الإجابة والصوت','Langue des réponses et de la voix','Idioma de respuesta y voz'],
    ['Type or record in your selected language. Ask Nova to translate pasted text. Somali speech is experimental; review its pronunciation and transcript.','Qor ama ku hadal luqadda aad dooratay. Weydii Nova inay turjunto qoraalka. Codka Soomaaliga waa tijaabo; hubi dhawaaqa iyo qoraalka.','اكتب أو سجّل باللغة المحددة. اطلب ترجمة النص. الصوت الصومالي تجريبي؛ راجع النطق والنص.','Écrivez ou enregistrez dans la langue choisie. Demandez une traduction. La voix somalie est expérimentale : vérifiez la prononciation et le texte.','Escriba o grabe en su idioma. Pida traducir texto. La voz somalí es experimental: revise la pronunciación y la transcripción.'],
    ['Record speech','Duub codka','سجّل الكلام','Enregistrer la voix','Grabar voz'],
    ['Finish and show text','Dhamee oo muuji qoraalka','إنهاء وعرض النص','Terminer et afficher le texte','Terminar y mostrar texto'],
    ['Record up to 60 seconds. Review the text before pressing Ask Nova. Audio is processed by the speech service and is not saved in this Workspace.','Duub ilaa 60 ilbiriqsi. Hubi qoraalka ka hor Weydii Nova. Codka waxaa farsameeya adeegga codka, halkan laguma kaydiyo.','سجّل حتى 60 ثانية. راجع النص قبل الإرسال. يُعالج الصوت بخدمة الكلام ولا يُحفظ هنا.','Enregistrez jusqu’à 60 secondes. Relisez avant l’envoi. Le son est traité par le service vocal et n’est pas enregistré ici.','Grabe hasta 60 segundos. Revise antes de enviar. El servicio de voz procesa el audio y no se guarda aquí.'],
    ['Continue work','Sii wad shaqada','تابع العمل','Continuer le travail','Continuar trabajo'],
    ['Summarize project','Soo koob mashruuca','لخّص المشروع','Résumer le projet','Resumir proyecto'],
    ['Find a file','Raadi fayl','ابحث عن ملف','Trouver un fichier','Encontrar archivo'],
    ['Search prior work','Raadi shaqadii hore','ابحث في العمل السابق','Rechercher le travail précédent','Buscar trabajo anterior'],
    ['Explain what changed','Sharax waxa isbeddelay','اشرح التغييرات','Expliquer les changements','Explicar cambios'],
    ['Suggest next action','Soo jeedi tallaabada xigta','اقترح الخطوة التالية','Suggérer la prochaine étape','Sugerir próximo paso'],
    ['Sign in','Soo gal','تسجيل الدخول','Se connecter','Iniciar sesión'],
    ['Sign out','Ka bax','تسجيل الخروج','Se déconnecter','Cerrar sesión'],
    ['Sign in to use Nova Workspace.','Soo gal si aad u isticmaasho Nova.','سجّل الدخول لاستخدام Nova.','Connectez-vous pour utiliser Nova.','Inicie sesión para usar Nova.'],
    ['Email','Iimaylka','البريد الإلكتروني','E-mail','Correo electrónico'],
    ['Password','Furaha sirta','كلمة المرور','Mot de passe','Contraseña'],
    ['Mrs. Nova Brain is ready when you are signed in.','Nova waa diyaar marka aad soo gasho.','Nova جاهزة بعد تسجيل الدخول.','Nova est prête après connexion.','Nova está lista al iniciar sesión.'],
    ['Mrs. Nova Brain is connected to this Nova Workspace.','Nova waxay ku xiran tahay goobtan shaqada.','Nova متصلة بمساحة العمل هذه.','Nova est connectée à cet espace.','Nova está conectada a este espacio.'],
    ['Voice is AI-generated. Press Read aloud to hear the answer.','Codka waxaa sameeya AI. Guji Kor u akhri si aad u maqasho jawaabta.','الصوت مولّد بالذكاء الاصطناعي. اضغط قراءة بصوت عالٍ لسماع الإجابة.','Voix générée par IA. Cliquez sur Lire à voix haute pour écouter.','Voz generada por IA. Pulse Leer en voz alta para escuchar.'],
    ['Trust labels: VERIFIED DATA · USER-SAVED INFORMATION · AI SUGGESTION','Calaamadaha: XOG LA XAQIIJIYAY · XOGTA ISTICMAALAHA · SOO JEEDINTA AI','التصنيفات: بيانات موثقة · معلومات محفوظة · اقتراح ذكاء اصطناعي','Libellés : DONNÉES VÉRIFIÉES · INFORMATIONS ENREGISTRÉES · SUGGESTION IA','Etiquetas: DATOS VERIFICADOS · INFORMACIÓN GUARDADA · SUGERENCIA IA'],
    ['Transfer a project','Koobi u wareeji mashruuc','نقل نسخة مشروع','Transférer un projet','Transferir proyecto'],
    ['Choose a project below. The recipient signs in and accepts its copy. Instructions are included; conversations and file text are optional. Original uploads, connected accounts, login and billing are not copied.','Hoos ka dooro mashruuc. Qaataha ayaa soo gala oo aqbala nuqulka. Tilmaamaha waa la koobiyeeyaa; wada hadalka iyo qoraalka faylku waa ikhtiyaar. Faylasha asalka, akoonnada ku xiran iyo lacag bixinta lama koobiyo.','اختر مشروعًا أدناه. يسجّل المستلم الدخول ويقبل النسخة. التعليمات مشمولة؛ المحادثات ونصوص الملفات اختيارية. لا تُنسخ الملفات الأصلية أو الحسابات المتصلة أو بيانات الدخول والفوترة.','Choisissez un projet. Le destinataire se connecte et accepte sa copie. Instructions incluses ; conversations et textes des fichiers facultatifs. Fichiers originaux, connexions et facturation exclus.','Elija un proyecto. El destinatario inicia sesión y acepta la copia. Incluye instrucciones; conversaciones y texto de archivos son opcionales. No copia archivos originales, conexiones, acceso ni facturación.'],
    ['Project to copy','Mashruuca la koobiyeeyo','المشروع المراد نسخه','Projet à copier','Proyecto para copiar'],
    ['Choose a project','Dooro mashruuc','اختر مشروعًا','Choisir un projet','Elegir proyecto'],
    ['No file is required. Create a project first if this account has none.','Fayl looma baahna. Marka hore samee mashruuc haddii uusan jirin.','لا يلزم ملف. أنشئ مشروعًا أولًا إن لم يوجد.','Aucun fichier requis. Créez d’abord un projet si nécessaire.','No necesita archivo. Cree primero un proyecto si no hay ninguno.'],
    ['Recipient account email','Iimaylka qaataha','بريد حساب المستلم','E-mail du destinataire','Correo del destinatario'],
    ['Include saved conversations and drafts','Ku dar wada hadalka iyo qoraallada','تضمين المحادثات والمسودات','Inclure conversations et brouillons','Incluir conversaciones y borradores'],
    ['Include saved file text (not original files)','Ku dar qoraalka faylasha (ma aha faylasha asalka)','تضمين نصوص الملفات دون الأصول','Inclure le texte des fichiers, sans les originaux','Incluir texto de archivos, sin originales'],
    ['Prepare selected project transfer','Diyaari wareejinta mashruuca','جهّز نقل المشروع','Préparer le transfert','Preparar transferencia'],
    ['Project instructions are included. Choose optional content before preparing the copy.','Tilmaamaha mashruuca waa ku jiraan. Dooro waxa kale ee la koobiyeeyo.','تعليمات المشروع مشمولة. اختر المحتوى الاختياري قبل إعداد النسخة.','Instructions incluses. Choisissez les éléments facultatifs avant la copie.','Incluye instrucciones. Elija contenido opcional antes de copiar.'],
    ['Cancel prepared transfer','Jooji wareejinta','إلغاء النقل','Annuler le transfert','Cancelar transferencia'],
    ['Incoming project copies','Nuqulka mashruucyada soo socda','نسخ المشاريع الواردة','Copies de projets reçues','Copias de proyectos recibidas'],
    ['Sign in to see copies offered to your email.','Soo gal si aad u aragto nuqullada laguu soo diray.','سجّل الدخول لرؤية النسخ المرسلة لبريدك.','Connectez-vous pour voir les copies proposées.','Inicie sesión para ver las copias ofrecidas.'],
    ['Create new workspace / project','Samee mashruuc cusub','إنشاء مساحة عمل / مشروع','Créer un espace / projet','Crear espacio / proyecto'],
    ['Title','Cinwaanka','العنوان','Titre','Título'],
    ['Description','Faahfaahinta','الوصف','Description','Descripción'],
    ['Create project','Samee mashruuc','إنشاء مشروع','Créer un projet','Crear proyecto'],
    ['Upload / add file','Soo geli fayl','رفع / إضافة ملف','Ajouter un fichier','Subir / añadir archivo'],
    ['Upload a document to make its extracted text available to Nova.','Soo geli dukumenti si Nova u akhrido qoraalkiisa.','ارفع مستندًا لإتاحة نصه المستخرج لـ Nova.','Ajoutez un document pour que Nova puisse lire son texte extrait.','Suba un documento para que Nova lea su texto extraído.'],
    ['Upload and add to workspace','Soo geli goobta shaqada','رفع وإضافة لمساحة العمل','Ajouter à l’espace de travail','Subir al espacio de trabajo'],
    ['Active projects','Mashruucyada firfircoon','المشاريع النشطة','Projets actifs','Proyectos activos'],
    ['Sign in to see projects.','Soo gal si aad u aragto mashruucyada.','سجّل الدخول لرؤية المشاريع.','Connectez-vous pour voir les projets.','Inicie sesión para ver proyectos.'],
    ['Recent work','Shaqadii dhowayd','العمل الأخير','Travaux récents','Trabajo reciente'],
    ['No recent work yet.','Weli shaqo ma jirto.','لا يوجد عمل حديث.','Aucun travail récent.','No hay trabajo reciente.'],
    ['Recent conversations','Wada hadalladii dhowaa','المحادثات الأخيرة','Conversations récentes','Conversaciones recientes'],
    ['No conversations yet.','Weli wada hadal ma jiro.','لا توجد محادثات.','Aucune conversation.','No hay conversaciones.'],
    ['Recent files','Faylashii dhowaa','الملفات الأخيرة','Fichiers récents','Archivos recientes'],
    ['No files yet.','Weli faylal ma jiraan.','لا توجد ملفات.','Aucun fichier.','No hay archivos.'],
    ['Saved / recent searches','Raadinta kaydsan / dhowayd','عمليات البحث المحفوظة / الأخيرة','Recherches enregistrées / récentes','Búsquedas guardadas / recientes'],
    ['Search above to save a search here.','Kor ka raadi si aad halkan ugu kaydiso.','ابحث أعلاه لحفظ البحث هنا.','Recherchez ci-dessus pour enregistrer une recherche.','Busque arriba para guardar una búsqueda.'],
    ['Assistant history','Taariikhda kaaliyaha','سجل المساعد','Historique de l’assistant','Historial del asistente'],
    ['Saved Nova Workspace messages you can reopen.','Farriimaha kaydsan ee aad dib u furi karto.','رسائل محفوظة يمكنك إعادة فتحها.','Messages enregistrés que vous pouvez rouvrir.','Mensajes guardados que puede volver a abrir.'],
    ['No assistant history loaded.','Taariikh wali lama soo gelin.','لم يُحمّل سجل المساعد.','Historique non chargé.','Historial sin cargar.'],
    ['Workspace search results','Natiijooyinka raadinta','نتائج البحث في مساحة العمل','Résultats de recherche','Resultados de búsqueda'],
    ['Enter a search above to find your saved projects, files, and conversations.','Kor ka raadi mashruucyada, faylasha iyo wada hadalka.','ابحث أعلاه للعثور على المشاريع والملفات والمحادثات.','Recherchez ci-dessus vos projets, fichiers et conversations.','Busque arriba proyectos, archivos y conversaciones.'],
    ['No active projects yet.','Weli mashruuc ma jiro.','لا توجد مشاريع نشطة.','Aucun projet actif.','No hay proyectos activos.'],
    ['No pending project copies for this account.','Nuqul sugaya akoonkan ma jiro.','لا توجد نسخ مشاريع معلّقة لهذا الحساب.','Aucune copie de projet en attente.','No hay copias pendientes para esta cuenta.'],
    ['Ask Nova to start your saved Workspace history.','Weydii Nova si taariikhdu u kaydsanto.','اسأل Nova لبدء سجل مساحة العمل.','Interrogez Nova pour commencer votre historique.','Pregunte a Nova para iniciar el historial.'],
    ['No workspace matches.','Wax la mid ah lama helin.','لا توجد نتائج مطابقة.','Aucun résultat.','No hay coincidencias.'],
    ['Reopen conversation','Dib u fur wada hadalka','إعادة فتح المحادثة','Rouvrir la conversation','Reabrir conversación'],
    ['Accept and copy this project','Aqbal oo koobi mashruucan','قبول ونسخ المشروع','Accepter et copier ce projet','Aceptar y copiar proyecto'],
    ['🎤 Talk','🎤 Hadal','🎤 تحدث','🎤 Parler','🎤 Hablar'],
    ['▶ Start Nova','▶ Bilow Nova','▶ ابدأ Nova','▶ Lancer Nova','▶ Iniciar Nova'],
    ['⏹ Stop','⏹ Jooji','⏹ إيقاف','⏹ Arrêter','⏹ Detener'],
    ['🎙 Read aloud','🎙 Kor u akhri','🎙 قراءة بصوت عالٍ','🎙 Lire à voix haute','🎙 Leer en voz alta'],
    ['Voice ready.','Codku waa diyaar.','الصوت جاهز.','Voix prête.','Voz lista.'],
    ['Generating speech…','Codka ayaa la diyaarinayaa…','جارٍ توليد الصوت…','Génération de la voix…','Generando voz…'],
    ['Audio ready. Press Play below if you do not hear it.','Codku waa diyaar. Guji Play hoos haddii aadan maqlin.','الصوت جاهز. اضغط تشغيل أدناه إذا لم تسمعه.','Son prêt. Appuyez sur Lecture ci-dessous si vous ne l’entendez pas.','Audio listo. Pulse Reproducir abajo si no lo escucha.'],
    ['Speech is unavailable. Your text remains available.','Codka lama heli karo. Qoraalku weli waa jiraa.','الصوت غير متاح. النص ما زال متاحًا.','Voix indisponible. Le texte reste accessible.','Voz no disponible. El texto sigue disponible.'],
    ['Recording. Press Finish when you are done.','Duubistu way socotaa. Guji Dhamee markaad dhammayso.','جارٍ التسجيل. اضغط إنهاء عند الانتهاء.','Enregistrement. Appuyez sur Terminer à la fin.','Grabando. Pulse Terminar al finalizar.'],
    ['Transcribing speech…','Codka ayaa qoraal loo rogayaa…','جارٍ تحويل الكلام إلى نص…','Transcription en cours…','Transcribiendo voz…'],
    ['Transcript ready. Review or correct the words, then press Ask Nova.','Qoraalku waa diyaar. Hubi ama sax, kadib guji Weydii Nova.','النص جاهز. راجعه أو صححه ثم اضغط اسأل Nova.','Texte prêt. Relisez ou corrigez, puis envoyez à Nova.','Texto listo. Revise o corrija y pulse Preguntar a Nova.'],
    ['Nova is working on your request…','Nova waxay ka shaqaynaysaa codsigaaga…','Nova تعمل على طلبك…','Nova traite votre demande…','Nova procesa su solicitud…'],
    ['Nova response is ready. Review the result below.','Jawaabtu waa diyaar. Hoos ka hubi.','الإجابة جاهزة. راجع النتيجة أدناه.','Réponse prête. Consultez le résultat ci-dessous.','Respuesta lista. Revise el resultado abajo.'],
    ['Select the project you want to copy first.','Marka hore dooro mashruuca aad koobiyeyso.','اختر المشروع المراد نسخه أولًا.','Choisissez d’abord le projet à copier.','Elija primero el proyecto para copiar.'],
    ['Session expired. Sign in again.','Fadhigu wuu dhammaaday. Mar kale soo gal.','انتهت الجلسة. سجّل الدخول مجددًا.','Session expirée. Reconnectez-vous.','Sesión caducada. Inicie sesión de nuevo.'],
    ['Temporary system error.','Cilad ku meel gaar ah.','خطأ مؤقت في النظام.','Erreur système temporaire.','Error temporal del sistema.'],
    ['Speech transcription is unavailable. Please type your request or try again.','Codka qoraal looma rogi karo hadda. Qor codsiga ama mar kale isku day.','تحويل الكلام غير متاح. اكتب طلبك أو حاول مجددًا.','Transcription indisponible. Écrivez votre demande ou réessayez.','Transcripción no disponible. Escriba o inténtelo de nuevo.'],
    ['Microphone could not start. Allow microphone access, or type your request.','Makarafoonku ma shaqayn. Oggolow makarafoonka ama qor codsiga.','تعذّر تشغيل الميكروفون. اسمح بالوصول أو اكتب الطلب.','Microphone indisponible. Autorisez-le ou écrivez votre demande.','No se pudo iniciar el micrófono. Autorícelo o escriba.']
  ];
  rows = rows.concat([
  [
    "results",
    "natiijooyin",
    "نتائج",
    "résultats",
    "resultados"
  ],
  [
    "active",
    "firfircoon",
    "نشط",
    "actif",
    "activo"
  ],
  [
    "pending",
    "sugaya",
    "معلّق",
    "en attente",
    "pendiente"
  ],
  [
    "accepted",
    "la aqbalay",
    "مقبول",
    "accepté",
    "aceptado"
  ],
  [
    "canceled",
    "la joojiyay",
    "ملغى",
    "annulé",
    "cancelado"
  ],
  [
    "project",
    "mashruuc",
    "مشروع",
    "projet",
    "proyecto"
  ],
  [
    "file",
    "fayl",
    "ملف",
    "fichier",
    "archivo"
  ],
  [
    "conversation",
    "wada hadal",
    "محادثة",
    "conversation",
    "conversación"
  ],
  [
    "user",
    "isticmaale",
    "مستخدم",
    "utilisateur",
    "usuario"
  ],
  [
    "assistant",
    "kaaliye",
    "مساعد",
    "assistant",
    "asistente"
  ],
  [
    "project_created",
    "Mashruuc la sameeyay",
    "تم إنشاء مشروع",
    "Projet créé",
    "Proyecto creado"
  ],
  [
    "conversation_created",
    "Wada hadal la bilaabay",
    "تم بدء محادثة",
    "Conversation créée",
    "Conversación creada"
  ],
  [
    "message_created",
    "Farriin la kaydiyay",
    "تم حفظ رسالة",
    "Message enregistré",
    "Mensaje guardado"
  ],
  [
    "file_created",
    "Fayl la kaydiyay",
    "تم حفظ ملف",
    "Fichier enregistré",
    "Archivo guardado"
  ],
  [
    "search_saved",
    "Raadin la kaydiyay",
    "تم حفظ بحث",
    "Recherche enregistrée",
    "Búsqueda guardada"
  ],
  [
    "Continue this thread",
    "Sii wad wada hadalkan",
    "تابع هذه المحادثة",
    "Continuer cette conversation",
    "Continuar conversación"
  ],
  [
    "Instructions + {conversations} conversations + {files} file texts. Expires {date}",
    "Tilmaamo + {conversations} wada hadal + {files} qoraal fayl. Wuxuu dhacayaa {date}",
    "تعليمات + {conversations} محادثات + {files} نصوص ملفات. تنتهي {date}",
    "Instructions + {conversations} conversations + {files} textes. Expiration {date}",
    "Instrucciones + {conversations} conversaciones + {files} textos. Caduca {date}"
  ],
  [
    "Instructions + {conversations} conversations + {files} file texts. Recipient signs in and accepts under Incoming project copies. No email was sent.",
    "Tilmaamo + {conversations} wada hadal + {files} qoraal fayl. Qaataha ayaa soo gala oo aqbala nuqulka. Iimayl lama dirin.",
    "تعليمات + {conversations} محادثات + {files} نصوص ملفات. يسجّل المستلم الدخول ويقبل النسخة في قسم النسخ الواردة. لم يُرسل بريد.",
    "Instructions + {conversations} conversations + {files} textes. Le destinataire se connecte et accepte dans Copies de projets reçues. Aucun e-mail envoyé.",
    "Instrucciones + {conversations} conversaciones + {files} textos. El destinatario inicia sesión y acepta en Copias recibidas. No se envió correo."
  ],
  [
    "Project copy prepared for recipient acceptance.",
    "Nuqulka waa diyaar si qaatahu u aqbalo.",
    "النسخة جاهزة لقبول المستلم.",
    "Copie prête pour acceptation.",
    "Copia lista para aceptación."
  ],
  [
    "Transfer canceled. The recipient cannot accept it.",
    "Wareejinta waa la joojiyay. Qaatahu ma aqbali karo.",
    "أُلغي النقل. لا يمكن للمستلم قبوله.",
    "Transfert annulé. Le destinataire ne peut plus l’accepter.",
    "Transferencia cancelada. El destinatario no puede aceptarla."
  ],
  [
    "Accepted project copy. You can now work on it in Ask Nova.",
    "Nuqulka waa la aqbalay. Waxaad kaga shaqayn kartaa Weydii Nova.",
    "تم قبول النسخة. يمكنك العمل عليها في اسأل Nova.",
    "Copie acceptée. Vous pouvez travailler avec Nova.",
    "Copia aceptada. Puede trabajar con Nova."
  ],
  [
    "Created project {id}.",
    "Mashruuc {id} ayaa la sameeyay.",
    "تم إنشاء المشروع {id}.",
    "Projet {id} créé.",
    "Proyecto {id} creado."
  ],
  [
    "Added {title} to Nova Workspace.",
    "{title} ayaa lagu daray Nova.",
    "أُضيف {title} إلى Nova.",
    "{title} ajouté à Nova.",
    "{title} añadido a Nova."
  ],
  [
    "Selected {title}. Enter your request in Ask Nova.",
    "{title} ayaa la doortay. Ku qor codsiga Weydii Nova.",
    "تم تحديد {title}. أدخل طلبك في اسأل Nova.",
    "{title} sélectionné. Saisissez votre demande à Nova.",
    "{title} seleccionado. Escriba su solicitud a Nova."
  ],
  [
    "Opened saved file {id}.",
    "Faylka {id} ayaa la furay.",
    "فُتح الملف {id}.",
    "Fichier {id} ouvert.",
    "Archivo {id} abierto."
  ],
  [
    "Continuing conversation {id}.",
    "Wada hadalka {id} ayaa la sii wadaa.",
    "متابعة المحادثة {id}.",
    "Poursuite de la conversation {id}.",
    "Continuando conversación {id}."
  ],
  [
    "Network error. Saved work was not changed.",
    "Cilad xiriir. Shaqada kaydsan lama beddelin.",
    "خطأ في الاتصال. لم يتغير العمل المحفوظ.",
    "Erreur réseau. Travail enregistré inchangé.",
    "Error de red. El trabajo guardado no cambió."
  ],
  [
    "Access denied.",
    "Gelitaanka waa la diiday.",
    "رُفض الوصول.",
    "Accès refusé.",
    "Acceso denegado."
  ],
  [
    "Not found / unavailable.",
    "Lama helin / lama heli karo.",
    "غير موجود / غير متاح.",
    "Introuvable / indisponible.",
    "No encontrado / no disponible."
  ],
  [
    "Request failed.",
    "Codsigu wuu fashilmay.",
    "فشل الطلب.",
    "Échec de la demande.",
    "Error en la solicitud."
  ],
  [
    "Sign in to ask Mrs. Nova Brain.",
    "Soo gal si aad u weydiiso Nova.",
    "سجّل الدخول لسؤال Nova.",
    "Connectez-vous pour interroger Nova.",
    "Inicie sesión para preguntar a Nova."
  ],
  [
    "Signed in",
    "Soo galay",
    "تم تسجيل الدخول",
    "Connecté",
    "Sesión iniciada"
  ],
  [
    "Sign-in failed",
    "Soo geliddu way fashilantay",
    "فشل تسجيل الدخول",
    "Échec de connexion",
    "Error al iniciar sesión"
  ],
  [
    "Signed in. Nova Workspace is available.",
    "Waad soo gashay. Nova waa diyaar.",
    "تم تسجيل الدخول. Nova متاحة.",
    "Connexion réussie. Nova est disponible.",
    "Sesión iniciada. Nova está disponible."
  ],
  [
    "Sign in before recording speech.",
    "Soo gal ka hor duubista codka.",
    "سجّل الدخول قبل التسجيل.",
    "Connectez-vous avant d’enregistrer.",
    "Inicie sesión antes de grabar."
  ],
  [
    "Recording is unavailable in this browser. Type your request in Ask Nova.",
    "Duubistu ma shaqayso. Ku qor codsiga Weydii Nova.",
    "التسجيل غير متاح في هذا المتصفح. اكتب الطلب.",
    "Enregistrement indisponible. Écrivez votre demande.",
    "No se puede grabar en este navegador. Escriba su solicitud."
  ],
  [
    "Recording failed. Try typing your request.",
    "Duubistu way fashilantay. Qor codsiga.",
    "فشل التسجيل. اكتب طلبك.",
    "Échec de l’enregistrement. Écrivez votre demande.",
    "Error al grabar. Escriba su solicitud."
  ],
  [
    "Enter at least 2 characters to search Nova Workspace.",
    "Qor ugu yaraan 2 xaraf si aad u raadiso.",
    "أدخل حرفين على الأقل للبحث.",
    "Saisissez au moins 2 caractères.",
    "Escriba al menos 2 caracteres."
  ],
  [
    "Searched Nova-owned workspace content only.",
    "Waxaa la raadiyay xogta goobtan shaqada oo keliya.",
    "تم البحث في محتوى مساحة العمل فقط.",
    "Recherche limitée à l’espace de travail.",
    "Búsqueda limitada al espacio de trabajo."
  ],
  [
    "Choose a file to upload with the existing /api/upload capability.",
    "Dooro fayl aad soo geliso.",
    "اختر ملفًا لرفعه.",
    "Choisissez un fichier à ajouter.",
    "Elija un archivo para subir."
  ],
  [
    "No response from Mrs. Nova Brain.",
    "Nova ma jawaabin.",
    "لا توجد إجابة من Nova.",
    "Aucune réponse de Nova.",
    "Sin respuesta de Nova."
  ],
  [
    "No description saved.",
    "Faahfaahin lama kaydin.",
    "لا يوجد وصف محفوظ.",
    "Aucune description enregistrée.",
    "No hay descripción guardada."
  ],
  [
    "No readable text was extracted from this file.",
    "Qoraal la akhrin karo lagama helin faylkan.",
    "لم يُستخرج نص مقروء من الملف.",
    "Aucun texte lisible extrait.",
    "No se extrajo texto legible."
  ],
  [
    "Continue this Mrs. Nova Brain thread.",
    "Sii wad wada hadalka Nova.",
    "تابع محادثة Nova.",
    "Continuez cette conversation avec Nova.",
    "Continúe esta conversación con Nova."
  ],
  [
    "Running…",
    "Way shaqaynaysaa…",
    "جارٍ التنفيذ…",
    "Exécution…",
    "Procesando…"
  ],
  [
    "Stopped.",
    "Waa la joojiyay.",
    "تم الإيقاف.",
    "Arrêté.",
    "Detenido."
  ],
  [
    "Say or type something first.",
    "Marka hore hadal ama qor.",
    "تحدث أو اكتب أولًا.",
    "Parlez ou écrivez d’abord.",
    "Hable o escriba primero."
  ],
  [
    "Reading the current Nova result.",
    "Jawaabta Nova ayaa la akhrinayaa.",
    "جارٍ قراءة نتيجة Nova.",
    "Lecture du résultat Nova.",
    "Leyendo el resultado de Nova."
  ],
  [
    "Nova destinations",
    "Goobaha Nova",
    "وجهات Nova",
    "Rubriques Nova",
    "Secciones Nova"
  ],
  [
    "AMICOR Nova demo",
    "Bandhigga AMICOR Nova",
    "عرض AMICOR Nova",
    "Démonstration AMICOR Nova",
    "Demostración AMICOR Nova"
  ],
  [
    "Workspace search and Mrs. Nova Brain",
    "Raadinta goobta shaqada iyo Nova",
    "البحث في مساحة العمل وNova",
    "Recherche et Nova",
    "Búsqueda y Nova"
  ],
  [
    "Project transfers",
    "Wareejinta mashruucyada",
    "نقل المشاريع",
    "Transferts de projets",
    "Transferencias de proyectos"
  ],
  [
    "Workspace dashboard",
    "Dashboard-ka goobta shaqada",
    "لوحة مساحة العمل",
    "Tableau de bord",
    "Panel de trabajo"
  ],
  [
    "Nova spoken answer",
    "Jawaabta codka Nova",
    "إجابة Nova الصوتية",
    "Réponse vocale Nova",
    "Respuesta hablada de Nova"
  ],
  [
    "Read Nova answer aloud",
    "Kor u akhri jawaabta Nova",
    "اقرأ إجابة Nova بصوت عالٍ",
    "Lire la réponse Nova",
    "Leer la respuesta de Nova"
  ],
  [
    "Stop Nova reading",
    "Jooji akhrinta Nova",
    "أوقف قراءة Nova",
    "Arrêter la lecture Nova",
    "Detener lectura de Nova"
  ],
  [
    "Talk to Nova",
    "La hadal Nova",
    "تحدث إلى Nova",
    "Parler à Nova",
    "Hablar con Nova"
  ],
  [
    "Start Nova with this request",
    "Ku bilow Nova codsigan",
    "ابدأ Nova بهذا الطلب",
    "Lancer Nova avec cette demande",
    "Iniciar Nova con esta solicitud"
  ],
  [
    "Stop Nova voice",
    "Jooji codka Nova",
    "أوقف صوت Nova",
    "Arrêter la voix Nova",
    "Detener voz de Nova"
  ]
]);
  var codes = ['en', 'so', 'ar', 'fr', 'es'];
  var catalog = Object.create(null);
  rows.forEach(function (row) { catalog[row[0]] = row; });
  var current = 'en';
  function t(key, values) {
    key = String(key || "");
    var row = catalog[key];
    var text = row ? row[codes.indexOf(current)] : key;
    return text.replace(/\{(\w+)\}/g, function (_, name) { return values && values[name] !== undefined ? String(values[name]) : '{' + name + '}'; });
  }
  function apply() {
    document.documentElement.setAttribute('lang', current);
    document.documentElement.setAttribute('dir', current === 'ar' ? 'rtl' : 'ltr');
    document.querySelectorAll('[data-nova-i18n]').forEach(function (el) { el.textContent = t(el.getAttribute('data-nova-i18n')); });
    document.querySelectorAll('[data-nova-placeholder]').forEach(function (el) { el.setAttribute('placeholder', t(el.getAttribute('data-nova-placeholder'))); });
    document.querySelectorAll('[data-nova-label]').forEach(function (el) { el.setAttribute('aria-label', t(el.getAttribute('data-nova-label'))); });
  }
  function setLanguage(code) {
    current = codes.indexOf(code) >= 0 ? code : 'en';
    try { localStorage.setItem('nova-workspace-screen-language', current); } catch (_) {}
    apply();
    window.dispatchEvent(new Event('nova-language-change'));
  }
  window.NovaWorkspaceLanguage = { t: t, apply: apply, setLanguage: setLanguage, current: function () { return current; }, catalog: catalog };
  try { current = localStorage.getItem('nova-workspace-screen-language') || 'en'; } catch (_) {}
  if (codes.indexOf(current) < 0) current = 'en';
  document.getElementById('screen-language').value = current;
  apply();
})();
