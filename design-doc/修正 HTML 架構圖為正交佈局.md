# **軟體架構可視化之正交圖形佈局 (Orthogonal Graph Layout) 深度解析與 AI 生成文件修正指南**

## **導論與核心問題剖析**

在現代軟體工程、系統架構設計以及資料庫實體關聯（ER 模型）的視覺化領域中，圖形佈局（Graph Layout）的品質直接決定了資訊傳遞的效率與專業度。當工程團隊或架構師依賴人工智慧（AI）工具來自動生成軟體架構圖或程式碼核心關聯圖時，經常會面臨一個致命的視覺缺陷：AI 生成的佈局預設採用非正交（Non-orthogonal）的直接連線，導致畫面中充斥著隨機角度的斜線與不可預測的邊緣交叉 1。這種現象在圖論與視覺化工程中被稱為「毛線球效應」（Hairball Effect），極大地提高了讀者的認知負荷，使得追蹤元件間的依賴關係與資料流向變得異常困難。  
研究證據指出，圖形佈局的「可讀性」（Readability）應被定義為使用者在該佈局上尋找與追蹤資訊的效率，並透過完成拓撲任務的耗時與正確率來精確衡量 3。在評估不同的佈局策略時，傳統的力導向佈局（Force-Directed Layout）雖然在尋找局部相鄰節點時有其優勢，但整體架構的結構化表達則遠遠不及正交圖形佈局（Orthogonal Graph Layout）2。正交佈局強制所有代表系統元件的節點放置於虛擬的幾何網格（Grid）上，且所有的依賴關係線（邊）僅能以絕對的水平或垂直線段進行佈線 2。這種嚴格的 90 度直角約束不僅徹底消除了對角線帶來的視覺雜訊，更為 UML 類別圖、微服務架構圖、業務流程圖提供了高度一致性與專業級的網格化結構 1。  
本報告旨在深入剖析正交圖形佈局的底層數學模型、演算法基礎，以及其在現代 HTML/SVG 前端環境中的具體渲染實作機制。進一步地，針對由 AI 依照初始 diagram\_creation\_guide.md 提示生成的非正交架構圖，本報告將提供一套極度詳盡的解決方案。這包含了直接重構 HTML 前端 DOM 元素與 SVG 路徑的工程實踐，以及徹底改寫 diagram\_creation\_guide.md 提示工程（Prompt Engineering）指示的規範，確保未來 AI 生成的圖表在拓撲佈局與路徑尋找上，嚴格遵循無交叉、最小彎折的正交美學標準。

## **正交圖形佈局的演算法基礎與美學最佳化標準**

要將隨機散佈的軟體元件轉化為高度可讀的正交架構圖，本質上是一個多目標的受約束最佳化問題（Constrained Multi-objective Optimization Problem）。正交圖形佈局演算法必須在滿足數學拓撲限制的前提下，極大化整體的美學價值 4。

### **核心美學評估與優化標準**

正交佈局演算法的設計原則嚴格遵循以下依照優先權遞減排列的美學標準，這些標準共同決定了最終輸出圖表的清晰度與專業感 2：

1. **邊緣交叉最小化（Minimal Number of Edge Crossings）：** 交叉的線條是破壞圖形可讀性的最大元凶。演算法在初期必須判斷輸入圖形的拓撲性質。如果該圖形屬於平面圖（Planar Graphs），演算法必須確保最終生成的正交圖形擁有絕對的 0 交叉；若為無法避免交叉的非平面圖（Non-planar Graphs），則必須透過啟發式演算法將交叉數量壓至理論最低極限，並在計算過程中將這些交叉點暫時替換為虛擬節點（Dummy Nodes），以維持後續計算的純粹性 2。  
2. **彎折點數量最小化（Bend Minimization）：** 在正交路徑中，每一次的 90 度轉折都會打斷視覺追蹤的流暢度，增加使用者的認知負擔。演算法需確保線條在連接兩個架構元件時，使用最少的轉折次數。理想狀態下為直接的水平或垂直線，其次為單次轉折（L 型），再次為兩次轉折（Z 型或 U 型）2。  
3. **整體繪製面積最小化與緊湊度（Compactness Optimization / Minimal Area）：** 架構圖應避免鬆散的元件分佈。透過消除網格中未使用的空白區域並緊密排列節點，演算法致力於生成最小可能的總體繪製面積，使龐大的軟體架構圖更容易在單一螢幕或有限的文件頁面內完整顯示與列印 2。  
4. **總邊長最小化（Total Edge Length Minimization）：** 在確保不重疊的前提下，縮短所有連接線的總長度不僅能間接減少交叉發生的機率，還能使圖形的視覺重心更為集中，使大腦更容易理解元件間的群聚關係（Clustering）5。

### **拓撲、形狀與壓實：正交演算法的三階段架構**

為了達成上述極其複雜的美學要求，經典的正交圖形生成演算法（如 yFiles 等商業引擎所採用之架構）將運算過程嚴格劃分為三個獨立但相互依賴的計算階段 2。

| 演算法階段 (Phase) | 核心任務與數學機制剖析 | 預期輸出結果與狀態 |
| :---- | :---- | :---- |
| **1\. 拓撲階段 (Topology Step)** | 此階段的目標是修復並確立圖形的拓撲結構。演算法首先執行平面性測試（Planarity Testing），尋找圖形的平面嵌入（Planar Embedding）。接著，演算法會決定所有節點在平面上的相對位置，更重要的是，確立每條邊離開特定節點邊界的「絕對順序」。透過這種排序，演算法能識別出所有潛在的邊緣交叉，並利用優化路徑最小化交叉數。為確保後續計算不發生邊緣重疊，殘留的交叉會被轉換為圖形理論中的虛擬節點 2。 | 生成一個確定了元件相對位置、拓撲關係與邊緣離開順序的初步佈局圖，但尚未決定確切的二維座標與線段物理長度。 |
| **2\. 形狀階段 (Shape Step)** | 定義每條邊的幾何正交結構。演算法在此階段決定哪些線段必須是絕對水平或垂直的，並精確計算出彎折（Bends）發生的拓撲位置。此階段的數學優化重點完全聚焦於「最小化彎折數量」，透過網路流量演算法（Network Flow Algorithms）等技術，在保持拓撲一致性的前提下，將視覺結構的複雜度降至最低 2。 | 產生一個具有 90 度直角特徵且確定了轉折點邏輯的正交草圖（Orthogonal Shape），但整體的網格配置可能過於鬆散。 |
| **3\. 壓實階段 (Compaction Step)** | 此為將理論轉換為視覺像素的關鍵步驟。演算法必須將形狀階段所定義的拓撲結果對齊至確切的絕對網格點（Grid Points）上。透過受約束的二次規劃（Constrained Quadratic Programming）或基於物理模型的模擬退火（Simulated Annealing）演算法，系統在不破壞已建立之拓撲與正交形狀的前提下，極大化壓縮總繪製面積，並最小化總邊長與彎折處的跨距 4。 | 輸出最終的精確二維網格座標 (X, Y)，圖形具備極高的緊湊度、無效空白消除，且完美遵循正交美學標準。 |

### **Kandinsky 模型與高維節點邊界處理**

在早期的正交佈局科學研究中，演算法普遍建立在一個嚴格且不切實際的數學假設上：每個節點在四個方向（上、下、左、右）上，各自最多只能有一條邊進出 2。這意味著任何節點的最大拓撲度數（Maximum Degree）被死板地限制為 4。然而，在實際的軟體架構圖、資料庫實體關聯圖（ER Diagram）或 UML 類別圖中，核心伺服器叢集、主資料表或基礎類別（即高維度節點）往往需要同時連接數十個其他系統元件 2。  
為突破此一物理瓶頸，現代先進的正交佈局演算法全面導入了 **Kandinsky 模型** 2。該模型透過放寬傳統的正交邊界約束，允許單一節點的同一側邊界擁有多條連接線（Multiple edges per side）。Kandinsky 模型的幾何處理邏輯極為優雅：在同一側的連接線群中，位於正中心的線可無任何彎折地垂直退出節點邊界；而位於其左側的所有線段，則在離開節點邊界後立即向左微彎（Bend slightly left）；同理，右側的線段則向右微彎 2。這種機制不僅成功支援了高維度節點的視覺化，更在嚴謹的數學層面上保證了正交結構的純粹性與整體網格的協調性。

### **模擬退火與全域/局部最佳化 (Simulated Annealing)**

在最終的網格分配與節點座標定位上，為了達到繪圖面積與總邊長的雙重最小化，先進的演算法必須結合局部（Local）與全域（Global）的改進機制 5。局部改進通常依賴貪婪演算法（Greedy Optimization），反覆測試將單一節點移動到相鄰的更佳位置，或交換兩個相鄰節點的位置以縮短連線。然而，這種局部優化極易陷入局部最小值（Local Minima）的陷阱，導致整體圖形無法達到最佳緊湊度。  
為了解決這個問題，全局改進機制引入了受限二次規劃以及模擬退火概念的隨機位移機制 5。模擬退火允許系統在計算初期接受一定機率的「較差解」（即暫時增加邊長或面積的位移），透過強迫特定節點群落集體平移或擴張，幫助整體網路佈局跳脫局部最小值的束縛。隨著計算過程的「溫度」降低，演算法逐漸收斂，最終透過反覆的垂直與水平壓實（Compaction in vertical and horizontal directions），產出絕對最佳化的佈局結果 5。

## **網格尋路與正交連接線佈線機制 (Grid Routing Algorithms)**

當軟體架構的各個元件（節點）已經在畫布上確定了位置，如何計算兩個元件之間的「最佳正交路徑」便成為另一個獨立且複雜的計算幾何問題。在互動式 HTML 環境或現代圖形編輯器中，即時的正交連接線佈線（Orthogonal Connector Routing）演算法必須具備極低的延遲，這通常依賴於建立在二元搜尋樹（BST, Binary Search Tree）之上的圖形資料結構，以實現實時的拖拽重算與避障功能 6。

### **參考點、切片與邊界框 (Bounding Boxes & Slices)**

為了尋找完全不穿透其他軟體元件（即障礙物）的正交路徑，佈線演算法首先必須將連續的 HTML 畫布或 SVG 座標空間，離散化為可供演算法尋路的網格系統（Route Grid）7。具體的空間切割與建構步驟包含：

1. **繪製引導參考線 (Lead Lines & Rulers)：** 演算法會從畫布上每一個元件物件（Object Bounding Box）的四個邊界中心點，以及物件的幾何中心，向外發射平行的水平與垂直射線。每個矩形物件會產生 8 條引導線。這些射線會穿越整個畫布，直到碰撞到其他物件的邊界或畫布的最邊緣。這些線條將構成潛在路徑的邊（Edges）6。  
2. **定義空間切片 (Slices)：** 這些橫豎交錯的引導線將整個畫布空間切割成無數的微小矩形區塊。這些區塊依據其空間特徵被嚴格分類為三種切片：角落切片（Corner slice，位於障礙物周圍）、邊緣切片（Edge slice，與障礙物相鄰）以及內部切片（Internal slice，位於無障礙的開放空間）7。  
3. **生成交叉節點 (Intersections & Reference Points)：** 當兩條引導線在空間中相交時，便形成了一個交叉點。這些交叉點以及根據切片類型額外生成的參考點，即為尋路演算法圖形結構中的「節點」（Nodes）。相鄰節點之間若沒有被任何實體元件阻擋，便會建立雙向的正交連接線，並將兩點之間的像素距離（Distance in pixels）設定為該邊的權重值 6。

### **啟發式尋路：Dijkstra 與 A\* 演算法之對比**

當由參考點與垂直/水平邊組成的無向尋路圖建構完成後，系統即可套用圖論中的最短路徑演算法來尋找最佳連接方案。  
在較為初階的實作中，經常採用 Dijkstra 演算法 6。Dijkstra 會以起始點為中心，均勻向外擴展，尋找總權重（即物理像素距離）最低的路徑。雖然 Dijkstra 演算法確保了幾何距離上的絕對最短，但它完全忽視了正交佈局中極為重要的「彎折數最小化」美學標準。這經常導致找出的路徑雖然短，但卻呈現出鋸齒狀或階梯狀的連續轉折，極大地破壞了架構圖的可讀性與專業感 6。  
因此，現代專業的軟體架構圖工具（如 yFiles 等引擎）在底層佈線時，全面採用了基於 A\* (A-Star) 的啟發式演算法 6。A\* 演算法透過成本函數 ![][image1] 進行路徑評估。其中 ![][image2] 為起點到目前節點的實際距離成本，而 ![][image3] 則是目前節點到終點的預估成本。在正交佈線的特殊應用場景中，A\* 演算法會被大幅度修改：除了計算距離外，演算法會對**方向改變（即發生 90 度彎折）施加極高額的懲罰權重（Penalty weights）** 9。這種巧妙的數學懲罰機制迫使尋路演算法在決策時，寧可選擇繞行較遠的物理距離，也要盡可能保持長距離的直線延伸。這完美契合了正交佈局減少彎折的美學需求，確保了連接線的乾淨俐落 9。

### **動態拖拽修正與鏡像資料點 (Mirror Data Points)**

在現代互動式 HTML 應用程式中，使用者經常會使用滑鼠拖拽架構節點，或手動調整連接線的自定義轉折點（Custom Turning Points）。此時，元件的位移會立刻導致原本依照 A\* 計算出來的正交路徑失效，甚至產生線條穿越實體圖形的嚴重錯誤 8。  
為了應對這種動態環境，先進的前端實作（如基於 SVG 渲染的圖表系統）會在記憶體中維護兩組平行的點座標數據：dataPoints 與 renderKeyPoints 8。

* dataPoints：代表儲存於底層資料結構中，需要持久化存檔的自定義轉折點邏輯。  
* renderKeyPoints：代表當前螢幕上實際繪製出正交折線的動態計算點。

當節點被拖曳，導致原本的正交線條不再維持絕對水平或垂直時，演算法不會直接丟棄使用者的自定義路徑，而是透過「平行線修正」（Correction based on parallel lines）或「前後點修正」（Correction based on front and back points）機制來補償位移。在此過程中，系統會計算一組稱為 mirrorDataPoints 的映射數據，強制建立 dataPoints 與實際渲染點之間的一對一對應關係 8。透過比較這些鏡像點的索引變化與相對位置偏移，系統能夠在微秒級別內精準推算出新的安全中繼點（Mid-points），並重新將非正交的斜線強制導回嚴格的曼哈頓正交路徑，從而確保在任何激烈的互動拖曳下，連接線依然維持完美正交且不穿透任何圖形 8。

## **SVG 與 HTML 環境下的前端渲染工程實踐**

當底層演算法完成了複雜的拓撲排列與網格尋路計算後，最終的座標數據必須透過網頁技術精確地渲染到使用者的螢幕上。在現代網頁開發中，業界絕對標準的做法是利用 HTML5 的可縮放向量圖形（SVG, Scalable Vector Graphics）技術，特別是其中的 \<path\> 元素，來描繪這些正交連接線 10。相較於 HTML Canvas 依賴像素繪製，SVG 提供了保留 DOM 結構、支援 CSS 樣式繼承以及無損縮放的巨大優勢。

### **SVG \<path\> 核心路徑資料語法解析**

SVG 的 \<path\> 元素透過其極度強大且精煉的 d 屬性（Data Attribute）來接收一系列的繪圖指令。這些指令定義了從起點到終點，每一個轉折、直線與曲線的絕對幾何行為 10。  
路徑資料語法採用前綴表示法（Prefix Notation），由單一英文字母指令與其後續跟隨的數字參數組合而成。在 SVG 規範中，指令的大小寫具有決定性的意義：**大寫字母代表絕對座標（Absolute Coordinates），小寫字母代表相對座標（Relative Coordinates）** 10。在繪製需要精確對齊架構元件邊界框的正交佈局時，通常強烈建議全程使用大寫的絕對座標指令。  
以下為在正交架構圖渲染中，最為核心的 SVG 指令集剖析：

| SVG 指令 (Command) | 語法名稱與參數結構 | 在正交圖形佈局中的具體應用與渲染機制 |
| :---- | :---- | :---- |
| **M** (或 m) | Moveto (移動到) (x y)+ | 這是所有路徑的絕對起點。指令指示渲染引擎抬起虛擬畫筆，在不繪製任何線條的情況下，直接將當前座標移動到參數指定的 x, y 點。在架構圖中，每一條獨立的元件連接線必定以 M x,y 作為資料字串的開頭 10。 |
| **L** (或 l) | Lineto (畫直線) (x y)+ | 指示畫筆從當前位置繪製一條直線到指定的絕對座標 x,y。雖然 L 指令可以繪製任何角度的斜線，但在嚴格的正交佈局實踐中，除非用於繪製箭頭或特殊形狀，否則在連線路徑上通常會被 H 與 V 指令所取代，以避免人為計算浮點數誤差導致的非絕對正交斜角 10。 |
| **H** (或 h) | Horizontal Lineto (水平線) x+ | **正交佈局渲染的靈魂指令。** 它指示畫筆從當前位置開始，保持目前的 y 座標絕對不變，僅繪製一條純粹的水平線直到確切的絕對 x 座標。這在語法層面上直接強制了線條呈現 0 度或 180 度的正交特徵，消除了任何斜線的可能性 10。 |
| **V** (或 v) | Vertical Lineto (垂直線) y+ | **正交佈局渲染的另一個靈魂指令。** 它指示畫筆從當前位置開始，保持目前的 x 座標絕對不變，繪製一條純粹的垂直線直到確切的絕對 y 座標。這保證了線條只能以 90 度或 270 度延展 10。 |
| **Z** (或 z) | Closepath (封閉路徑) 無參數 | 強制將當前路徑的終點與最初的 M 起始點直接連接，形成一個封閉的多邊形。在架構圖中，這通常用於繪製自定義的實心箭頭（Markers）或是封閉的系統邊界框 10。 |

**純直角曼哈頓路徑 (Manhattan Path) 渲染範例：**  
若演算法決策需從系統服務 A 的輸出埠 (100, 100\) 畫一條正交線至系統服務 B 的輸入埠 (300, 200)，基於正交美學，線條不能直接穿越斜角。必須先向右水平移動，再向下垂直移動。對應的 HTML SVG 程式碼將極度簡潔：

XML  
\<path d\="M 100,100 H 300 V 200" fill\="none" stroke\="black" stroke-width\="2" /\>

### **利用貝茲曲線與橢圓弧線渲染美學圓角**

純粹由 90 度直角與銳利折線構成的正交圖形，雖然在邏輯上絕對正確，但在視覺心理學上往往顯得過於生硬且具壓迫感。現代專業軟體設計圖工具（如 Draw.io、yFiles、Inkscape 等）皆支援在正交轉折處加入柔和的圓角（Curved corners or Rounded orthogonal routing），這能顯著提升圖表的美觀度與閱讀舒適度，而此功能純粹是基於美學的視覺增強（Aesthetic improvement）9。  
在 SVG 環境中，渲染平滑圓角可以透過二次貝茲曲線（Q 指令）、三次貝茲曲線（C 指令），或最為推薦的橢圓弧線（A 指令）來實現 10。  
在處理正交架構圖的圓角時，**橢圓弧線（Elliptical Arc Curve, A 指令）** 是在程式邏輯上最容易精確控制半徑的選擇，因為它不需要去推算抽象的控制點（Control Points）10。 A 指令的完整參數結構為：(rx ry x-axis-rotation large-arc-flag sweep-flag x y) 10。

* **rx, ry (半徑)：** 設定假想橢圓的水平與垂直半徑。對於架構圖中標準的正交圓角，這兩個值通常被設定為相等的數值，代表一個正圓的圓角半徑（例如 8 8，代表 8 像素的圓弧半徑）10。  
* **x-axis-rotation (旋轉角度)：** 指示整個橢圓相對於當前座標系的旋轉角度。由於我們繪製的是標準的正交圓角，此值永遠設定為 0。  
* **large-arc-flag (大弧/小弧標誌)：** 控制要繪製橢圓上較長的那段弧線還是較短的那段。由於 90 度的正交轉角永遠只跨越四分之一圓（短路徑），此值必須絕對設定為 0 10。  
* **sweep-flag (掃描方向標誌)：** 這是一個二元值，控制圓弧是從起點開始以順時針（設為 1）或逆時針（設為 0）方向繪製至終點 10。在實作 JavaScript 路徑生成器時，必須依據線條的行進方向（例如向右行進後向下轉，需順時針 1；向右行進後向上轉，需逆時針 0）來動態計算此值。  
* **x, y (終點座標)：** 圓弧結束的絕對座標位置 10。

**平滑圓角正交路徑渲染範例：**  
假設我們需從 (100, 100\) 連接至 (300, 200)，並希望在轉折處加入半徑為 10 像素的圓弧。  
邏輯為：從起點向右畫水平線至距離轉折點前 10 像素的位置 (290, 100)；接著畫一個半徑 10 的順時針圓弧，落於垂直線的起點 (300, 110)；最後垂直畫至終點。

XML  
\<path d\="M 100,100 H 290 A 10,10 0 0,1 300,110 V 200" fill\="none" stroke\="\#2563EB" stroke-width\="2" stroke-linejoin\="round" /\>

### **現代前端生態系統的深度整合 (Tailwind CSS, Vue, D3.js)**

在現代企業級架構可視化系統中，開發者極少手寫原始的 SVG 字串。高階工具（如 Viime-Path 生物代謝網路與架構可視化系統所展示的架構）會將底層強大的佈局演算法與資料驅動（Data-Driven）的現代 UI 框架進行深度結合，形成一套完整的無伺服器（Serverless）前端解決方案 15。

* **框架與狀態管理：** 利用 Vue.js 或 React 等響應式框架來管理系統中所有的節點狀態、依賴關聯以及 dataPoints。當使用者介面或查詢改變資料流時，框架的響應式系統會自動觸發虛擬 DOM（Virtual DOM）的重新計算，實現元件的即時更新 15。  
* **圖形渲染與互動引擎：** D3.js 被廣泛採用作為底層的渲染圖元庫。它負責將經過 WebCola（一種支援基於人類直覺的 HOLA 類人正交網路佈局演算法的約束優化函式庫）計算出的正交座標，精準綁定（Data Binding）到 SVG 的 \<path\> 與 \<rect\> 元素上，並提供極致流暢的全視角平移與縮放（Pan and Zoom）互動介面 15。  
* **樣式解耦與主題化：** 為了確保架構圖能完美融入企業儀表板的設計系統中，最先進的實踐是將圖形的幾何計算與視覺樣式徹底分離。透過結合 Tailwind CSS 與 DaisyUI 等實用優先（Utility-first）的樣式庫，架構圖中的節點背景顏色、字體大小、線條粗細與狀態高亮，皆可透過 CSS 類別（Classes）動態套用，而無需在龐大且難以維護的 SVG 結構中硬編碼（Hardcode）內聯樣式。這種作法不僅大幅縮減了 HTML 的體積，更確保了設計規範的絕對一致性 15。

## **現有技術生態與商業解決方案深度評估**

為了修正並完善由 AI 生成的架構圖，理解當前業界的主流渲染引擎與其原生能力至關重要。以下詳細對比了幾種核心的圖形可視化函式庫與商業 SDK：

| 引擎 / 函式庫名稱 | 技術特性與底層演算法支持層級 | 主要適用場景與架構限制 | 參考文獻文獻 |
| :---- | :---- | :---- | :---- |
| **yFiles (yWorks)** | 業界公認最頂尖的商業級圖表 SDK。內建極度成熟且高度優化的正交佈局演算法。全面支持複雜的 Kandinsky 模型，並提供自動修復拓撲、極致的彎折最小化計算與緊湊度壓實優化。開發者僅需輸入原始資料結構，引擎即可在一瞬間自動排出完美無瑕、無須人工介入對齊的正交網格圖。 | 適用於極度複雜的 UML 類別圖、大型微服務網路拓撲、精密電路圖與企業級業務流程圖。缺點為商業授權與維護成本極其高昂，不適合預算有限的開源專案。 | 1 |
| **JointJS / GoJS** | 主流的網頁互動圖表庫霸主。兩者皆提供開箱即用的強大正交路由機制（Orthogonal Routers）與精密的避障演算法。GoJS 在節點處理與記憶體優化上具有優勢；而 JointJS 則依賴開放的生態系，允許開發者高度自定義連結線的行為與 SVG 生成邏輯。 | 適用於需要高度自定義互動、即時拖拽重繪以及視覺編輯器的現代網頁應用。 | 17 |
| **WebCola \+ D3.js** | 學術界與開源界廣泛採用的方案。WebCola 基於約束的最佳化技術，能夠在 D3 的力導向模擬中強加水平與垂直的空間約束，從而實現類似 HOLA (Human-like Orthogonal Network Layout) 演算法的美學結構。D3.js 則提供了無與倫比的資料驅動 DOM 渲染能力。 | 適用於學術研究、客製化資料可視化儀表板，以及需深度整合至 React/Vue 框架的無伺服器架構圖應用（如 Viime-Path）。 | 15 |
| **mxGraph (Draw.io 核心)** | 極度成熟且開源的 XML 架構可視化結構。透過宣告式的樣式屬性配置（如直接在節點設定 edgeStyle=orthogonalEdgeStyle），底層引擎便會全自動接管並計算所有複雜的正交 SVG 路徑。 | 適用於靜態架構圖、文件夾帶圖表匯出，更是作為 AI 提示工程生成的完美、無痛中介格式。 | 18 |
| **Syncfusion EJ2** | 企業級的前端元件庫。提供輕量級且易於整合的 JavaScript Diagram 控件，內建對 Orthogonal 連接線段類型的原生支援。 | 適用於需在企業後台系統或管理儀表板中快速整合基本圖表功能的專案，開發成本極低。 | 20 |

## **AI 生成 HTML 佈局之具體手動與程式化修正方案**

針對使用者提出的核心痛點：AI 依據指示所生成的 HTML 架構圖發生了佈局非正交化（Not Orthogonalized）的現象，導致連線錯亂、難以辨認。這種現象的根本原因在於，目前的大型語言模型（LLMs）缺乏原生的二維空間幾何運算能力。當要求 AI 輸出直接的 HTML/SVG 時，若缺乏極度嚴密的空間公式約束，AI 預設會採用最簡單的歐幾里得幾何（Euclidean Geometry），直接提取起始點與終點的座標，並畫出中心點對中心點的最短直線。這種作法往往對應於 SVG 中的 \<line\> 標籤，或是僅包含單一 L 指令的 \<path\>，完全忽視了「先水平、後垂直」的正交網格幾何約束。  
要將這種混亂的 HTML 網頁重構為符合專業標準的正交佈局，必須依序執行以下深度的架構重構與 DOM 解析步驟：

### **步驟一：診斷與解構 AI 生成的錯誤 SVG 元素**

首先，必須檢查 HTML 檔案中的 \<svg\> 區塊，搜尋並標記出所有負責作為連接線的 \<line\> 元素，或是直接利用 d="M... L..." 的錯誤 \<path\> 元素。  
*AI 生成的典型錯誤（非正交斜線）範例：*

XML  
\<line x1\="100" y1\="50" x2\="400" y2\="300" stroke\="\#999" stroke-width\="2" /\>

### **步驟二：實作曼哈頓路徑 (Manhattan Routing) 的中繼點座標計算**

正交路徑的本質在於至少需要計算出一個或多個中繼轉折點（Turning Point），以強迫線條在網格上行進 11。對於最常見的單轉折或雙轉折連接，若已知元件 A 邊界上的起點為 ![][image4]，元件 B 邊界上的終點為 ![][image5]，且我們希望線條由起點的右側水平出發，並以水平方式連接到終點的左側，則必須在空間的中心處計算出一個垂直轉折的水平中繼點 ![][image6]：  
![][image7]  
這意味著路徑將會是：向右走到 ![][image6] \-\> 垂直向下（或上）走到目標的 ![][image8] 高度 \-\> 繼續向右水平走到 ![][image9]。

### **步驟三：靜態 SVG 的手動重構與指令替換**

將上述算出的 ![][image6] 套用至前述提及的 SVG 正交專屬指令 H 與 V 中，取代原本的 \<line\>。

1. M x1, y1（絕對定位至起點）。  
2. H x\_mid（畫純水平線至中繼 X 座標）。  
3. V y2（畫純垂直線降至終點所在的 Y 高度）。  
4. H x2（畫純水平線抵達最終目標的 X 座標）。

*依照上述邏輯修正後的正確 HTML 範例：*

XML  
\<path d\="M 100,50 H 250 V 300 H 400" fill\="none" stroke\="\#2563EB" stroke-width\="2" /\>

### **步驟四：導入全自動動態正交演算法 (JavaScript DOM Injection)**

對於具有數十個節點的龐大架構圖，手動計算 SVG 座標是不切實際的。更有效率的解決方案是，在 AI 生成的 HTML 檔案底部注入一段輕量級的 JavaScript 路由引擎（Routing Engine）。該引擎會自動解析所有代表架構元件的 DOM 節點，讀取它們的實際幾何大小與網頁位置，並動態運算出完美的正交 SVG \<path\> 屬性，完全覆蓋並取代 AI 的錯誤輸出。  
開發者可在 HTML 中加入以下經過優化的動態路由指令碼：

JavaScript  
/\*\*  
 \* 全自動正交路徑生成器 (Automatic Orthogonal Path Generator)  
 \* 讀取兩個 DOM 元素，精確計算其邊界框，並生成 100% 正交且附帶美學圓角的 SVG 路徑字串。  
 \* @param {HTMLElement} el1 \- 起始架構節點 (Source Node)  
 \* @param {HTMLElement} el2 \- 目標架構節點 (Target Node)  
 \* @param {Number} cornerRadius \- 轉折處的美學圓角半徑，預設 8px  
 \* @returns {String} 符合 SVG d 屬性的正交路徑字串  
 \*/  
function generateOrthogonalPath(el1, el2, cornerRadius \= 8) {  
    // 1\. 取得元件在 viewport 中的絕對物理邊界框 (Bounding Client Rect)  
    const rect1 \= el1.getBoundingClientRect();  
    const rect2 \= el2.getBoundingClientRect();

    // 2\. 假設預設路由邏輯：從節點 1 的右側中心，連接到節點 2 的左側中心  
    const startX \= rect1.right;  
    const startY \= rect1.top \+ rect1.height / 2;  
    const endX \= rect2.left;  
    const endY \= rect2.top \+ rect2.height / 2;

    // 3\. 計算空間的水平中點，作為 Z 型正交路徑的垂直轉折通道  
    const midX \= startX \+ (endX \- startX) / 2;

    // 若系統不需要平滑圓角，可直接回傳純直角字串：  
    // return \`M ${startX},${startY} H ${midX} V ${endY} H ${endX}\`;

    // 4\. 進階：產生帶有 SVG 橢圓弧 (A) 圓角的精緻路徑  
    // 判斷線條是向上還是向下轉折，以決定圓弧的 sweep-flag (掃描方向)  
    const isGoingDown \= endY \> startY;  
    const sweepFlag1 \= isGoingDown? 1 : 0; // 第一個轉折：水平轉垂直  
    const sweepFlag2 \= isGoingDown? 0 : 1; // 第二個轉折：垂直轉水平

    // 計算預留給圓弧的提前轉彎距離  
    const turn1X \= midX \- cornerRadius;  
    const turn1Y \= startY \+ (isGoingDown? cornerRadius : \-cornerRadius);  
    const turn2Y \= endY \- (isGoingDown? cornerRadius : \-cornerRadius);  
    const turn2X \= midX \+ cornerRadius;

    // 組裝帶有圓角的高級正交路徑 (M \-\> H \-\> A \-\> V \-\> A \-\> H)  
    return \`M ${startX},${startY}   
            H ${turn1X}   
            A ${cornerRadius},${cornerRadius} 0 0,${sweepFlag1} ${midX},${turn1Y}   
            V ${turn2Y}   
            A ${cornerRadius},${cornerRadius} 0 0,${sweepFlag2} ${turn2X},${endY}   
            H ${endX}\`;  
}

// 實作範例：遍歷資料集並套用至 SVG  
// const pathElement \= document.getElementById('connection-1');  
// const nodeA \= document.getElementById('database-server');  
// const nodeB \= document.getElementById('cache-server');  
// pathElement.setAttribute('d', generateOrthogonalPath(nodeA, nodeB));

透過在原始 HTML 中部署此等幾何計算腳本，開發者可以徹底根除 AI 生成頁面中連線交錯與斜線混亂的缺陷，利用前端瀏覽器的強大運算能力，瞬間還原出完美對齊網格的正交架構圖。

## **diagram\_creation\_guide.md 提示工程重構與系統約束指南**

如前所述，大型語言模型（包含所有先進的 AI）本質上是以機率處理文本（Tokens）的引擎，它們徹底缺乏對二維度空間、圖形拓撲、網格佈局與物理防撞機制的感知能力。如果不透過 Prompt Engineering 在前置指令中施加絕對嚴格的拓撲與屬性宣告約束，AI 將無可避免地退化為隨機發散的圖形生成狀態。  
為從根本上解決 AI 未來反覆產出不正交佈局的問題，必須依據 Draw.io、mxGraph 與現代系統架構可視化的嚴謹規範 18，徹底改寫指導 AI 決策的 diagram\_creation\_guide.md 文件。以下提供應寫入該 Markdown 指南的四大核心系統規則與結構範本。

### **核心規則一：強制套用宣告式的正交樣式屬性 (Declarative Styling)**

如果 AI 被指示生成的目標格式是中介資料結構（如 Draw.io 的 .drawio XML、.drawio.svg 或 .arch.json），絕對禁止讓 AI 自行推算座標。必須強迫 AI 在所有連接線的樣式定義字串中，無條件注入原生的正交路由屬性，將渲染的重責大任轉交給底層專業的 mxGraph 引擎。

* **請將以下英文強制指令精確寫入 MD 檔案中：**

For ALL connector edges representing relationships, dependencies, or data flows, you MUST explicitly define the routing style in the edge's style attribute.

1. You MUST include exactly edgeStyle=orthogonalEdgeStyle; in every single edge style string. 19  
   2. You are FORBIDDEN to use straight, unconstrained Euclidean lines (edgeStyle=none;) or arbitrary force-directed structures.  
   3. For professional architecture aesthetics, chain these parameters: edgeStyle=orthogonalEdgeStyle;html=1;rounded=1;orthogonalLoop=1;jettySize=auto; to enable clean 90-degree routes with smoothed corners. 19

### **核心規則二：強制網格對齊與曼哈頓幾何座標約束**

若系統流程強制要求 AI 直接輸出原始的 HTML/SVG 網頁源碼（無中介引擎協助），則必須在提示詞中詳細定義 H 與 V 指令的物理意義，並強迫其遵循曼哈頓路徑。

* **請將以下英文強制指令精確寫入 MD 檔案中：**

When generating raw SVG \<path\> elements for architectural connectors, you lack visual spatial awareness. Therefore, you are STRICTLY PROHIBITED from using direct \<line\> tags or diagonal \<path d="M x1 y1 L x2 y2"\> statements that create diagonal visual noise.

1. Mentally assume a strict rectilinear grid placement for all system nodes.  
   2. You MUST construct all connections as Manhattan Paths, using horizontal (H) and vertical (V) SVG commands exclusively.  
   3. Do not connect center-to-center blindly. Route from the absolute bounds of the source node to the bounds of the target.  
   4. Default Routing Formula for AI logic: Compute a midpoint X. Construct path strictly as: d="M \[startX\], H \[midpointX\] V H \[endX\]". Do not deviate from this rectilinear structure.

### **核心規則三：防範「標籤湯」(Tag Soup) 與確保拓撲結構合法性**

AI 在面對長篇幅的系統架構文件（如複雜的微服務關聯或 ER 模型 XML/SVG）時，極易因上下文長度限制（Context Window）而產生無效的層次結構、重複的 ID 或是孤立無父節點的元素。這種混亂結構被稱為「標籤湯」（Tag Soup），不僅破壞渲染引擎解析，更會引發尋路演算法崩潰 21。

* **請將以下英文強制指令精確寫入 MD 檔案中：**

The generated code must be a coherent, valid structural block, not unstructured tag soup. Your output is evaluated by a machine, not a human. 21

1. **Global Uniqueness:** Every architectural cell, node, and edge id MUST be globally unique within the document tree. 19  
   2. **Explicit Geometry:** Every visual vertex (node) MUST contain an explicitly defined geometry object (e.g., \<mxGeometry x="..." y="..." width="..." height="..." as="geometry" /\>). 19  
   3. **Topological Validation:** Every edge MUST have source and target attributes that flawlessly match the exact IDs of existing, declared vertex nodes. Floating edges are completely forbidden unless simulating a sequence diagram lifeline. 19  
   4. Escape all XML special characters in labels strictly (& \-\> &, \< \-\> \<). 19  
   5. Do NOT include arbitrary conversational fillers, methodology explanations, or markdown padding outside the requested code block. Deliver pure, structurally sound code. 21

### **核心規則四：架構分層解耦 (Decoupling Topology from Styling)**

為了大幅降低 AI 在單一文字生成步驟中處理「邏輯拓撲」與「視覺幾何座標」的龐大認知負擔，指導指南必須強迫 AI 將問題拆解，採用三階段的宣告流程 2。

* **請將以下英文強制指令精確寫入 MD 檔案中：**

To prevent cognitive overload and spatial confusion, generate the diagram logically in three decoupled phases:

1. **Topology Phase:** Declare and isolate all physical nodes (servers, databases, components). Assign them distinct grid coordinates, organizing them into logical tiers (e.g., Presentation layer at Y=100, Application layer at Y=300, Data layer at Y=500).  
   2. **Relationship Phase:** Declare the edges connecting these nodes based solely on dependencies.  
   3. **Orthogonal Rendering Phase:** Apply the mandatory orthogonalEdgeStyle to the declared relationships, effectively offloading the routing complexity to the rectilinear renderer. 2

## **結論**

在企業級軟體架構可視化與系統文件工程的專業領域中，圖表佈局的精確度、幾何結構的邏輯性與視覺上的純淨度，直接決定了跨部門技術溝通的成敗。由非正交斜線與隨機連接所產生的視覺雜訊（毛線球效應），會嚴重阻礙架構師、開發者與營運團隊對複雜系統結構（如龐大的微服務相依性叢集、深層的資料庫關聯）的理解與決策。  
本報告以極高的技術粒度，詳盡論證了正交圖形佈局（Orthogonal Graph Layout）在美學標準、拓撲平面化以及圖論優化上的絕對優越性。透過深入解構其背後處理高維度節點的 Kandinsky 模型、執行空間壓實的模擬退火機制，以及基於二元搜尋樹與 A\* 演算法並施加彎折懲罰的高級網格路由尋路機制，確立了正交佈局演算法的理論基石。  
同時，針對實體前端工程的 HTML 與 SVG 渲染環境，本報告清晰地拆解了 M, H, V, A 指令在建構曼哈頓路徑中的物理意義，並提供了立即可用的 JavaScript 動態路由修正腳本，賦予開發者無痛覆蓋並徹底修正 AI 錯誤輸出的能力。  
最重要的是，面對大型語言模型在空間感知領域的先天物理缺陷，本報告提供了可用於全面升級 diagram\_creation\_guide.md 的決定性提示工程（Prompt Engineering）架構與規範。透過嚴格約束 AI 套用宣告式正交屬性（orthogonalEdgeStyle）、強制規範曼哈頓幾何路由邏輯、並透過防範「標籤湯」以確保文檔樹狀拓撲的絕對合法性，軟體開發與文件撰寫團隊將能夠全面駕馭並收斂 AI 的生成行為。這不僅能一勞永逸地解決佈局混亂的問題，更能確保未來的自動化工具穩定、高效地產出具備極致緊湊度、零無效交叉且符合最高業界專業美學標準的正交軟體架構圖。

#### **引用的著作**

1. 檢索日期：5月 31, 2026， [https://www.yfiles.com/the-yfiles-sdk/features/automatic-layouts/orthogonal-layout\#:\~:text=The%20orthogonal%20layout%20arranges%20graph,technical%20or%20structured%20data%20visualizations.](https://www.yfiles.com/the-yfiles-sdk/features/automatic-layouts/orthogonal-layout#:~:text=The%20orthogonal%20layout%20arranges%20graph,technical%20or%20structured%20data%20visualizations.)  
2. About Orthogonal Layout \- yFiles, 檢索日期：5月 31, 2026， [https://www.yfiles.com/the-yfiles-sdk/features/automatic-layouts/orthogonal-layout](https://www.yfiles.com/the-yfiles-sdk/features/automatic-layouts/orthogonal-layout)  
3. Comparing the Readability of the Force-Directed and Orthogonal Graph Layout \- Diva-Portal.org, 檢索日期：5月 31, 2026， [https://www.diva-portal.org/smash/get/diva2:1472455/FULLTEXT01.pdf](https://www.diva-portal.org/smash/get/diva2:1472455/FULLTEXT01.pdf)  
4. Orthogonal Layout \- Nevron Vision for .NET 2026.1, 檢索日期：5月 31, 2026， [https://helpdotnetvision.nevron.com/UsersGuide\_Layouts\_Orthogonal\_Layout.html](https://helpdotnetvision.nevron.com/UsersGuide_Layouts_Orthogonal_Layout.html)  
5. (PDF) Graph Compact Orthogonal Layout Algorithm \- ResearchGate, 檢索日期：5月 31, 2026， [https://www.researchgate.net/publication/295075594\_Graph\_Compact\_Orthogonal\_Layout\_Algorithm](https://www.researchgate.net/publication/295075594_Graph_Compact_Orthogonal_Layout_Algorithm)  
6. Bukk94/OrthogonalConnectorRouting: Algorithm for orthogonal connector routing \- GitHub, 檢索日期：5月 31, 2026， [https://github.com/Bukk94/OrthogonalConnectorRouting](https://github.com/Bukk94/OrthogonalConnectorRouting)  
7. Routing Orthogonal Diagram Connectors in JavaScript | by Geeksplainer \- Medium, 檢索日期：5月 31, 2026， [https://medium.com/swlh/routing-orthogonal-diagram-connectors-in-javascript-191dc2c5ff70](https://medium.com/swlh/routing-orthogonal-diagram-connectors-in-javascript-191dc2c5ff70)  
8. Orthogonal lines in drawing technology support custom turning points | by pubuzhixing, 檢索日期：5月 31, 2026， [https://pubuzhixing.medium.com/orthogonal-lines-in-drawing-technology-support-custom-turning-points-ef7ebb3fb1fb](https://pubuzhixing.medium.com/orthogonal-lines-in-drawing-technology-support-custom-turning-points-ef7ebb3fb1fb)  
9. Connectors \- Inkscape Wiki, 檢索日期：5月 31, 2026， [https://wiki.inkscape.org/wiki/Connectors](https://wiki.inkscape.org/wiki/Connectors)  
10. Paths — SVG 2, 檢索日期：5月 31, 2026， [https://www.w3.org/TR/SVG2/paths.html](https://www.w3.org/TR/SVG2/paths.html)  
11. SVG Basics—Creating Paths With Line Commands \- Vanseo Design, 檢索日期：5月 31, 2026， [https://vanseodesign.com/web-design/svg-paths-line-commands/](https://vanseodesign.com/web-design/svg-paths-line-commands/)  
12. SVG, Geometry — and a dash of JavaScript \- DEV Community, 檢索日期：5月 31, 2026， [https://dev.to/madsstoumann/svg-geometry-and-a-dash-of-javascript-3f9l](https://dev.to/madsstoumann/svg-geometry-and-a-dash-of-javascript-3f9l)  
13. An Interactive Guide to SVG Paths • Josh W. Comeau, 檢索日期：5月 31, 2026， [https://www.joshwcomeau.com/svg/interactive-guide-to-paths/](https://www.joshwcomeau.com/svg/interactive-guide-to-paths/)  
14. The SVG \`path\` Syntax: An Illustrated Guide \- CSS-Tricks, 檢索日期：5月 31, 2026， [https://css-tricks.com/svg-path-syntax-illustrated-guide/](https://css-tricks.com/svg-path-syntax-illustrated-guide/)  
15. Viime-Path: An Interactive Metabolic Pathway Generation Tool for Metabolomics Data Analysis \- bioRxiv, 檢索日期：5月 31, 2026， [https://www.biorxiv.org/content/10.1101/2023.03.07.531550v1.full.pdf](https://www.biorxiv.org/content/10.1101/2023.03.07.531550v1.full.pdf)  
16. (PDF) Viime-Path: An Interactive Metabolic Pathway Generation Tool for Metabolomics Data Analysis \- ResearchGate, 檢索日期：5月 31, 2026， [https://www.researchgate.net/publication/369158877\_Viime-Path\_An\_Interactive\_Metabolic\_Pathway\_Generation\_Tool\_for\_Metabolomics\_Data\_Analysis](https://www.researchgate.net/publication/369158877_Viime-Path_An_Interactive_Metabolic_Pathway_Generation_Tool_for_Metabolomics_Data_Analysis)  
17. JointJS vs. GoJS: Comparison between Two Leading JavaScript Diagramming Libraries, 檢索日期：5月 31, 2026， [https://www.jointjs.com/blog/jointjs-vs-gojs](https://www.jointjs.com/blog/jointjs-vs-gojs)  
18. drawio — AI agent skill | explainx.ai, 檢索日期：5月 31, 2026， [https://explainx.ai/skills/bahayonghang/drawio-skills/drawio](https://explainx.ai/skills/bahayonghang/drawio-skills/drawio)  
19. draw-io-diagram-generator | Agent Skills Library \- Awesome MCP Servers, 檢索日期：5月 31, 2026， [https://mcpservers.org/agent-skills/github/draw-io-diagram-generator](https://mcpservers.org/agent-skills/github/draw-io-diagram-generator)  
20. Orthogonal connector in EJ2 JavaScript Diagram control | Syncfusion®, 檢索日期：5月 31, 2026， [https://ej2.syncfusion.com/javascript/documentation/diagram/connectors/connector-segments/connector-orthogonal](https://ej2.syncfusion.com/javascript/documentation/diagram/connectors/connector-segments/connector-orthogonal)  
21. image-generator.md \- hugohe3/ppt-master \- GitHub, 檢索日期：5月 31, 2026， [https://github.com/hugohe3/ppt-master/blob/main/skills/ppt-master/references/image-generator.md](https://github.com/hugohe3/ppt-master/blob/main/skills/ppt-master/references/image-generator.md)

[image1]: <data:image/png;base64,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>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACcAAAAaCAYAAAA0R0VGAAAB7klEQVR4Xu2VTyhlURzHfxrMxoIwKX9KygJZWGpIWclK2NkbC4upSVNKNmyUaSJl5SU7C0ohK1nZECUbspiUpCaDURYzfH/dc3Xu953zePe9YvE+9a13Pr9zz7n3vnPOFcnxNhSyeC/sm8TlgUW2yEP+IHVcSINhk6zzn0VM/iEfWWZCA/KLZUxakUuWmfAX+cwyAx5ZpKIdGUN+mja/dt9glcgcMmnaui4nkE3ke9jJgY7XydJFiwTraQ3ZQ4aQu0gP/82dItsS1CskuKkFZNq48ueeUXSJ6EOkpF+SJ9b2b6tdbRyjbzfceVrnPtfIDrmQdWSLJaMDfnG4b1a7zTim1/qtdV6T6vQvdzErL2ywEXFPqu6D1db16OoXUibuuroSloYfyBVLmwVJHrTK4fQYYWejb5DrtQ5nk0BOWNosSvIACYfLdzibY+SW3BFyY37z5lJ0LW6wtPkk0Uk7THvVciG+m+uToPbVcj3GDSDF4v5c6VdC+6VE19MFMo/USDBoU6RHgM8vifvGR5F7ZJkLBtc1L+K76AwZZAlKkW6Whi4JDmUXvnmeCU/1ED3RfRfpmearpYse0OMsbWYkOtmBaTdbjjlEGlnG4FUPOYXsIitIPdV86A5MsEyDc4meoVkn7tsrQIpY5sjx1jwBPBRuHahYexYAAAAASUVORK5CYII=>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAaCAYAAADFTB7LAAACI0lEQVR4Xu2WTUhUURiGv34wWkRQKxHEJCJoY1Ap6CaUEIncVO5cBLaMwJRWLhR/wCBS3InhJoigli3CdfQHbVq4sU0EEaFECWKS3+v57sy57z1nuF4HdDEPvMzM83333Dtnzj13RGrsPydY5OS4Zdec1DSyjNCmecgyJ4c0rzUNXIgxq9nU/Ne8pVqM7+JOVJTTms8sKzEl7gJ7uRBgRvOAZQFeavpYxvgr7gLzkLcvD7nHQmOe5puaHyz3AM7ZzJKpE9f4XnNR80rzKNVR5ptmiKWBn+ye5rB9vqNZ0nSXOrLgXM9ZMu3iLnBO808zYZ/hferNd5AHcPPi6ouaTs1XzQtz0+XWFMOanyyZN+IGWfEcvtmGlGcD3BXXh+2ISZZHslRuUC22fHokXiuBBtyZPquS3QaSmQ1xy15RxzLwqXSB5yVeK4GGUwF3jdyk+Rj94uoDnrtgbsFzPmel8phyVMINcKj5DJqPgYtA/Zznxs3xl024LJXH3Fmk3PDYc3hajNj76+ZjjyjUngXcE3s/5heM25I9f4o1zSdyOAB3Injneczob0n/hD447kzAJTfaL79gPBX3XI6CAbD3+VzVbGm+SHa27muWySWEZuKD5o9mnQsGjrnE0gf7VYgWcRs4kyz6EKGxMHtdkr0JE2Jj7QkMeoRlAZrE/SuqOpjdjywLgPV8jGW1wJ/V2NaRh1FNK8tqg8dUEfALXGFZo8ZBYxv65HaiV9X2jwAAAABJRU5ErkJggg==>

[image4]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAD8AAAAaCAYAAAAAPoRaAAACi0lEQVR4Xu2YS8gOURjHH/e7+mJhYUNIQsonWcglSeSykdhIWbB3qW+HFCWRbCWX3HY2bkXuC1aWEmWhkGsuyfX/78z7fef9v8/MnFevxWh+9W/m/M8zZ+aZ95xnZl6zmpr/hdHQQDVT2QD9VrNCdEHPoKHakcJX6IiaFaMbOq9mGbeg5WpWlKfQdDWLqPJ0V0ZaG/nsg66pWXGY/CA1PRi4VM2I8dB1aFXW3gZdhGb3RnSGxdBpaIj4E6BR4pXxBNqtpgeT52PCYwf0HTpoIW6shYq6N2t3kp/QTeiq+K+gHvHKOAndUdMjL4mp0Paofd/6YndF+53gUbY9ZmHcaVEf21Oidgo7oW9qeuQlcVzajOO0JAMszIKYmdBj8VI5mm15jv2RPynzGgy2MOvmR57HWsvPq4mkIAtxXH8eMyys1dSxPIZb6/FnxZtsYZaUJb/GWsdySQnqZ2lxKTF5rLTW419miklJfpO1juWSF7QM2prts8Jr3A9pE42J4Q0s4pKF4hrD8baIl5L8Huizmh48wRw1Lfj3sv1fWbvBemh11G6Ql/w5C315/eSANffnTd2U5B9Ch9T0OAVdUBOcgN5auIAR0F3oE/TcwkeQh3exhE+ON9Br7RBeWKjSvNlXzB+PyS9QU+BxWpBdNlo4qccKaFbU5q/NipuHd7ExZW+SLJqs1PMsJO8tLSa/UE2h7DqaaCu4gKJx5pqfDFlirceyPUY8wuQXqRnBN9EbahaxDjqjZhvwTfCDhWXCLaut8sXC9Pfg0rud7fPrksVqc193L/TfQe+hj+Y/evUmJsE1zjX9L2ClL6v2h6EHFn6Iv/lDoj90GRqnHanwzW2YmhWBH2cT1aypqan5A3AtjhBxDq/+AAAAAElFTkSuQmCC>

[image5]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAD8AAAAaCAYAAAAAPoRaAAACzUlEQVR4Xu2YWchNURTHl3km8SCkDEmiZEjeZErmkoQylDI8SYbyhoiSSF4lQ6Y3L6Yi8wNP3kgUkSHyYJ7//2/t46677j737k+fh6Pzq3/fXv+97jl377P32ud+IiUl/wvdobbeTGUx9MubBaIn9Bjq6DtS+AQd8GbBGAud9mYjrkEzvFlQHkEjvFmPIi93T1dpxnh2QZe8WXA4+HbejMHEad409IcuQ3NCvAE6C435k9EyTIKOQx2cPxDq5rxGPIS2eTMGB89jIsYm6Bu0VzSvt2hF3RHiluQHdBW66PxX0BbnNeIodMObMfIGMQzaaOLbUsndatotwb3w95DodYebPsZDTZzCZuiLN2PkDeKwi5nHZUnaiK6CjFbQa9Gc3cZP5WD46z8/JHgZXIHvoKfQKuN7Fkj+uKpIShLN4/7z9BLdGpwQwrx1le5kOkvtdzlpPNaciaG9NvijQuyZJ7XXipKSxCeblzdVtG9WiO9DtyrdycyW2nu8DCKsM19Dux/0E9oZYs8Kqb1WlLyk6dCa0GaF93nfTbuLad8RPQ08nMB6nBNdQRbec7WJs+OL1Z8Fcr3ps2yHPngzBm8wzpuifvYEOct28IuguSa2+Ekip0T9WF/GHqnur7d0n4kOPo+70D5vxjgGnfEmOAK9Ff0CfLI3offQE9EfQTE+eyPAk+ONaFGsx3PRKs3JviDxwbOST/amg5+zBTmXZaI3jTFTqosKn3Z7E1tGQstDO++lqdGbJF9wWKkniA7ebq2MF6Y92rQtsUnLpVnJEVjxl0B9ocGi57VnvMQHQ6ZI7XdgzOtaHojeY4Do2b+0ursJngpXvFmPhdAJbyYyXyr7OVOsHnwUXf4xuPWuhzZ/XbJYrax0N8Gf2/4+PaoyFD+JSXCPc0//C1jpG1X7/aInBR/E3/xDojV0HurjO1Lhi0onbxYE1plB3iwpKSn5Ddsdm8LO+qBCAAAAAElFTkSuQmCC>

[image6]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACYAAAAaCAYAAADbhS54AAABiElEQVR4Xu2UuyuHURjHHySDDC5FYcKmDCw2ymBxK5uskmKQVYrRYFH+AIssbKSUDD+bS7EYRIkokYHJ5ft1nuN9fie59NPvJ51PfXqf5z1P77m+RyQSiUT+FwtwGrZoPgvHYfV7RQ5YhUvwGj7BVrgJ9+Cjqcsqw5KsUgl8gTeaM6Y5gavlGRE3kEHNO2Bh0vxjCiSZZMiUuL66woaP4Fb+9goVhS8Unl0elW+Rza0bgHPhS8sQbNM4HNgEvNK4GJ7BMlgPU3Ad5sFDeAJ7tZYcwAuTe9bEfZP1pUFbGhzIDBzVmJ17uLVVGp/DfngJa/Qd6/nzePyklvW5Bes07pP0SX+5M/vwFk7CZnEd38FtW6SwttLk9uMV8Mjk/nB7GHNyHl5Ln5IPu03OrekxueU5yG3HXDmuvIdbZe9A1i5qXAt3TVvG2IE0iTtjpFySQfMMEdZ2SrLyzNs1XhF3TZxKZtfRG1xJe+fNwwaTs7Njk9/DDXE/CxmDD+J+mka4I277I5HIn+cV4dhXQfrA9DsAAAAASUVORK5CYII=>

[image7]: <data:image/png;base64,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>

[image8]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABIAAAAaCAYAAAC6nQw6AAABCUlEQVR4XmNgGAWjgLpgFhDHAzE/mng4EAujieEEjkB8Doj/A/EdJHEmqNhkJDG84DSUBmkCYRiog/LtkcRwAkkg5gVicQaIpu1Icj+B+AiUzQjEbxggaj4AMSdMETo4DsQ/GFDDCKTJDcr+zQDxKghYQ+WwApDEZixi3EhsZygbFnZYAUjCFInvARWDAR4kNgjgNSgIif+VARJG2MABIC5FF4QBJQaIYX+B+B2UDYo1dAAyPANdEB0YAXEwAyQWQQaZoEozGANxKJQNCzsU8AWIHyPx5zFAYgkZiDJADJECYlkgnokqDQEg282hbF0g/seAiGoYAKlBxxhAiAGSENczEOH/UTDAAAAZWDl437VuUgAAAABJRU5ErkJggg==>

[image9]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAaCAYAAAC3g3x9AAABB0lEQVR4XmNgGAWjYPCBRUC8HYiVoPw5QLwaiNnhKkgAh4B4IRDPB+J3QJwFxLOBeAoQH0FSRxQoY0C4CgT+A/EuIJYB4n9A/AdJjiiwFo0PMlAOylZGlgACNSD+AMR/gVgDTQ4rkGSAGIgNTGeABA0MgNRtQuJjBVEMuA08w4AqB2L/ROLDQQ4QG0HZj4D4MZIcIxD3IPGlkNggA08g8eEAJAGK1UlQ9iqoOC8QP4MpQgPRQHwSiDnQJUDgOgMkoBOg/C9Q/jQgFoSKIQNuIN6HLogMWIDYD4nPCsTuSHx0sIUBkdjtkSXIAdUMkPQpDcReQHwfVZo0cJsBEsbIeCKKilEwAgAADzUyzghT2nEAAAAASUVORK5CYII=>