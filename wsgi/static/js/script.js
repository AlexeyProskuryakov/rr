var refresh_sbrdt = function(sbrdt){
	$.post(
	"/subreddit/add_to_queue/"+sbrdt,
	function(){
		location.reload();
	}
	);
};


var post_change = function(fn, v_id, meth){
	$.get(
	"/post/"+meth+"/"+fn+"/"+v_id,
	function(result){
			console.log(result);
			if (result['ok'] == true){
				location.reload();
			}
		}
	);
};

$(function(){
    var element = $("#posts-chart").get(0);
    if (element == undefined) {
    	return;
    }
    console.log("found container: ", element);
    var name = $("#posts-chart").attr("chart_for");
    console.log("creating chart for: ", name);
    var data;
    console.log("starting request...");
    $.get(
    	"/chart/"+name,
        function(result){
			console.log("process response");

			var series = result['series'];
			var info_map = result['info'];

			console.log(series);
			console.log(info_map);

			var plot = $.plot("#posts-chart",
				series,
				{
					series: {
						lines: {
							show: false
						},
						points: {
							show: true
						}
					},
					grid: {
						hoverable: true,
						clickable: true
					},
					yaxis: {
						min: 0,
						max: 200,
					},
					zoom: {
						interactive: true
					},
					pan: {
						interactive: true
					},
					selection: {
						mode: "x"
					}
				}
			);

			$("<div id='tooltip'></div>").css({
					position: "absolute",
					display: "none",
					border: "1px solid #fdd",
					padding: "2px",
					"background-color": "#fee",
					opacity: 0.80
				}).appendTo("body");

			$("#posts-chart").bind("plothover", function (event, pos, item) {
					if (item) {
						$("#tooltip").html(info_map[item.datapoint[0]])
							.css({top: item.pageY+5, left: item.pageX+5})
							.fadeIn(200);
					} else {
						$("#tooltip").hide();
					}
				});

			$("#posts-chart").bind("plotclick", function (event, pos, item) {
					if (item) {
						plot.highlight(item.series, item.datapoint);
					}
			});

        }
    );
});
