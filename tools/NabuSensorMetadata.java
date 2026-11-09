import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import org.json.JSONObject;

/** app_process metadata reader; does not register listeners or change settings. */
public final class NabuSensorMetadata {
    public static void main(String[] args) throws Exception {
        android.os.Looper.prepare();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        SensorManager manager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        for (Sensor sensor : manager.getSensorList(Sensor.TYPE_ALL)) {
            JSONObject row = new JSONObject();
            row.put("name", sensor.getName());
            row.put("vendor", sensor.getVendor());
            row.put("version", sensor.getVersion());
            row.put("type", sensor.getType());
            row.put("string_type", sensor.getStringType());
            row.put("max_range", sensor.getMaximumRange());
            row.put("resolution", sensor.getResolution());
            row.put("power_mA", sensor.getPower());
            row.put("min_delay_us", sensor.getMinDelay());
            row.put("max_delay_us", sensor.getMaxDelay());
            row.put("reporting_mode", sensor.getReportingMode());
            row.put("wakeup", sensor.isWakeUpSensor());
            row.put("fifo_max", sensor.getFifoMaxEventCount());
            row.put("fifo_reserved", sensor.getFifoReservedEventCount());
            System.out.println(row);
        }
    }
}
